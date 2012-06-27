#!/usr/bin/env python

"""Exports video correlation data in Hive tables to GAE production.
"""

USAGE = """%prog [options] [hive_masternode] [table_name]

Reads lines from files representing the Hive table data for video correlations
as generated by map_reduce/hive/video_recommender.q.
"""

import optparse
import sys
import urllib2

import boto

import boto_util
import hive_mysql_connector
import oauth_util.fetch_url as oauth_fetcher


class VideoInfo(object):
    def __init__(self, key, index):
        self.key = key
        self.index = index
        self.best_matches = {}
        

def get_video_info(video_infos, vid_key):
    if vid_key not in video_infos:
        index = len(video_infos)
        video_infos[vid_key] = VideoInfo(vid_key, index)
    return video_infos[vid_key]
        
        
def add_score(video_infos, vid1_key, vid2_key, score):
    vid1_info = get_video_info(video_infos, vid1_key)
    vid2_info = get_video_info(video_infos, vid2_key)
    vid1_info.best_matches[vid2_info.index] = score


def upload_to_gae(video_infos):
    # TODO(benkomalo): actually implement once we've figured out the schema
    # in GAE. Right now it just makes a dummy call to GAE to ensure we have
    # proper access to make calls to it.
    try:
        oauth_fetcher.fetch_url("/api/v1/dev/version")
    except urllib2.URLError as e:
        print >> sys.stderr, "Unable to access GAE:"
        print >> sys.stderr, e


def main(table_location, options):
    boto_util.initialize_creds_from_file()

    # TODO(benkomalo): factor some of this boilerplate out to boto_util
    # Open our input connections.
    s3conn = boto.connect_s3()
    bucket = s3conn.get_bucket('ka-mapreduce')
    s3keys = bucket.list(
        prefix=table_location[len('s3://ka-mapreduce/'):] + '/')

    # Mapping of video key to the info on the other videos which best match
    # that video
    # vid_key -> VideoInfo
    video_infos = {}

    # Note: a table's data may be broken down into multiple files on disk.
    delimiter = '\01'
    lines_read = 0
    for key in s3keys:
        if key.name.endswith('_$.folder$'):
            # S3 meta data - not useful.
            continue

        contents = key.get_contents_as_string()
        for line in contents.split('\n'):

            if not line:
                # EOF
                break

            lines_read += 1
            parts = line.rstrip().split(delimiter)
            if len(parts) != 3:
                # TODO(benkomalo): error handling
                continue

            vid1_key, vid2_key, score = parts
    
            try: 
                score = float(score)
            except ValueError:
                # Some of the values were invalid - deal with it.
                # TODO(benkomalo): error handling.
                continue
            
            add_score(video_infos, vid1_key, vid2_key, score)
            
            if lines_read % 1000 == 0:
                print "Read %s lines..." % lines_read

    total_pairs = sum([len(info.best_matches)
                       for info in video_infos.values()])
    print "\nSummary of collected data:"
    print ("\tDetected %d videos, with a total of %d video pair data" %
           (len(video_infos), total_pairs))
    if raw_input("Proceed to upload? [Y/n]: ").lower() in ['', 'y', 'yes']:
        upload_to_gae(video_infos)


def parse_command_line_args():
    parser = optparse.OptionParser(USAGE)
    parser.add_option('--ssh_keyfile',
        help=('A location of an SSH pem file to use for SSH connections '
              'to the specified Hive machine'))

    options, args = parser.parse_args()
    if len(args) < 2:
        print >> sys.stderr, USAGE
        sys.exit(-1)

    return options, args


if __name__ == '__main__':
    options, args = parse_command_line_args()

    hive_masternode = args[0]
    table_name = args[1]
    
    hive_mysql_connector.configure(hive_masternode, options.ssh_keyfile)
    
    print "Fetching table info..."
    table_location = hive_mysql_connector.get_table_location(table_name)

    if not table_location:
        raise Exception("Can't read info about %s in Hive master %s" %
                        (hive_masternode, table_name))

    main(table_location, options)