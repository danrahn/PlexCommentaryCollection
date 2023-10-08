import math
import os
import requests
import time
import urllib
import xml.etree.ElementTree as ET
import yaml
import argparse
import sys
from urllib import parse
import json


class CommentaryCollection:
    def __init__(self):
        self.get_config()
        self.commentaries = {}


    def get_config(self):
        """Reads the config file from disk

        Required parameters:
            token - your Plex token

        Optional (but strongly encouraged):
            host: the host of your plex server. Defaults to localhost:32400 if not provided
            library_section: The library you want to parse for commentary tracks. Default to 1 if not provided
            collection_name: The name of the collection. Defaults to "Commentary Collection" if not provided
            keywords: A list of keywords to look for. Defaults to ['commentary'] if not provided
        """

        self.valid = False
        config_file = self.adjacent_file('config.yml')
        if not os.path.exists(config_file):
            print('Could not find config.yml! Make sure it\'s in the same directory as this script')
            return

        config = None
        with open(config_file) as f:
            config = yaml.load(f, Loader=yaml.SafeLoader)

        if not config:
            config = {}

        parser = argparse.ArgumentParser()
        parser.add_argument('-p', '--host', help='Plex host')
        parser.add_argument('-t', '--token', help='Your Plex token')
        parser.add_argument('-s', '--section', help='Library section to scan')
        parser.add_argument('-c', '--collection', help='Collection name')
        parser.add_argument('-k', '--keywords', help='Comma separated list of keywords to use when looking at audio track names')
        parser.add_argument('-v', '--verbose', help='Verbose output')

        cmd_args = parser.parse_args()
        self.token = self.get_config_value(config, cmd_args, 'token', prompt='Enter your Plex token')
        self.host = self.get_config_value(config, cmd_args, 'host', default='http://localhost:32400')
        self.section_id = self.get_config_value(config, cmd_args, 'section', default=None)
        self.verbose = self.get_config_value(config, cmd_args, 'verbose', default=False)
        if self.section_id.isnumeric():
            self.section_id = int(self.section_id)
        self.collection_name = self.get_config_value(config, cmd_args, 'collection', default='Commentary Collection')
        if cmd_args.keywords != None:
            self.keywords = [keyword.lower() for keyword in cmd_args.keywords.split(',')]
        elif 'keywords' in config:
            self.keywords = [keyword.lower() for keyword in config['keywords']]
        else:
            self.keywords = ['commentary']

        self.section_type = "movie"

        self.valid = True


    def get_config_value(self, config, cmd_args, key, default='', prompt=''):
        cmd_arg = None
        if key in cmd_args:
            cmd_arg = cmd_args.__dict__[key]

        if key in config and config[key] != None:
            if cmd_arg != None:
                # Command-line args shadow config file
                print(f'WARN: Duplicate argument "{key}" found in both command-line arguments and config file. Using command-line value ("{cmd_args.__dict__[key]}")')
                return cmd_arg
            return config[key]

        if cmd_arg != None:
            return cmd_arg

        if default == None:
            return ''

        if len(default) != 0:
            return default

        if len(prompt) == 0:
            return input(f'\nCould not find "{key}" and no default is available.\n\nPlease enter a value for "{key}": ')
        return input(f'\n{prompt}: ')


    def run(self):
        """Kick off the processing"""

        if not self.valid:
            return

        if not self.test_plex_connection():
            return

        self.get_section()

        root = self.get_all_items()
        item_count = len(root)
        print(f'Found {item_count} items to parse')
        processed = 0
        start = time.time()
        update_interval = 2
        next_update = update_interval
        groups = [root[i:min(item_count, i + 50)] for i in range(0, item_count, 50)]
        print(f'Breaking into {len(groups)} groups for parsing')
        for group in groups:
            processed += 1

            self.process_item_group(group)

            end = time.time()
            if (math.floor(end - start) >= next_update):
                next_update += update_interval
                print(f'Processed {processed} of {len(groups)} ({((processed / len(groups)) * 100):.2f}%) in {(end - start):.1f} seconds')

        print(f'\nDone! Processed {processed} movie{"" if item_count == 1 else "s"} in {time.time() - start:.2f} seconds')
        self.postprocess()


    def test_plex_connection(self):
        """
        Does some basic validation to ensure we get a valid response from Plex with the given
        host and token.
        """

        status = None
        try:
            status = requests.get(self.url('/')).status_code
        except requests.exceptions.ConnectionError:
            print(f'Unable to connect to {self.host} ({sys.exc_info()[0].__name__}), exiting...')
            return False
        except:
            print(f'Something went wrong when connecting to Plex ({sys.exc_info()[0].__name__}), exiting...')
            return False

        if status == 200:
            return True

        if status == 401 or status == 403:
            print('Could not connect to Plex with the provided token, exiting...')
        else:
            print(f'Bad response from Plex ({status}), exiting...')
        return False


    def get_section(self):
        """Returns the section object that the collection will be added to"""
        sections = self.get_json_response('/library/sections')
        if not sections or 'Directory' not in sections:
            return None

        sections = sections['Directory']
        find = self.section_id
        if type(find) == int:
            for section in sections:
                if int(section['key']) == int(find):
                    if section['type'] not in ['movie', 'show']:
                        print(f'Ignoring selected library section {find}, as it\'s not a movie or show library.')
                        break
                    print(f'Found section {find}: "{section["title"]}"')
                    self.section_type = section["type"]
                    return section

            print(f'Provided library section {find} could not be found...\n')

        print('\nChoose a library to scan:\n')
        choices = {}
        for section in sections:
            if section['type'] not in ['movie', 'show']:
                continue
            print(f'[{section["key"]}] {section["title"]}')
            choices[int(section['key'])] = section
        print()

        choice = input('Enter the library number (-1 to cancel): ')
        while not choice.isnumeric() or int(choice) not in choices:
            if choice == '-1':
                return None
            choice = input('Invalid section, please try again (-1 to cancel): ')

        self.section_id = int(choice)
        self.section_type = choices[int(choice)]["type"]
        print(f'\nSelected "{choices[int(choice)]["title"]}"\n')
        return choices[int(choice)]



    def get_all_items(self):
        """Returns all the media items from the library"""

        lib_type = 1 if self.section_type == 'movie' else 4
        url = f'{self.host}/library/sections/{self.section_id}/all?type={lib_type}&X-Plex-Token={self.token}'
        response = requests.get(url)
        data = ET.fromstring(response.content)
        response.close()
        return data


    def process_item_group(self, group):
        key = group[0].attrib['key']
        if len(group) > 1:
            key += ',' + ','.join([item.attrib['ratingKey'] for item in group[1:]])
        metadataItems = self.get_metadata(key)['Metadata']
        for metadata in metadataItems:
            metadata_id = metadata['ratingKey']
            if not metadata:
                return

            media_title = metadata['title']
            if self.section_type == 'show':
                media_title = f'{metadata["grandparentTitle"]} - S{str(metadata["parentIndex"]).rjust(2, "0")}E{str(metadata["index"]).rjust(2, "0")} - {media_title}'
            self.commentaries[media_title] = { 'collections': [], 'commentary': [], 'id': metadata_id, 'all_tracks' : [[] for _ in range(len(metadata['Media']))] }
            self.find_commentary_tracks(metadata, self.commentaries[media_title])

            self.commentaries[media_title]['collections'] = self.get_collections(metadata)


    def get_metadata(self, loc):
        """Retrieves the metadata for the item specified by loc"""

        url = f'{self.host}{loc}?X-Plex-Token={self.token}'
        attempts = 0
        while attempts < 3:
            attempts += 1
            try:
                metadata = self.get_json_response(loc)
                break
            except:
                if attempts != 3:
                    print(f'Failed to get metadata for {loc}, retrying...')
                    time.sleep(1) # This could be a network hiccup, wait for a second before retrying

        if attempts == 3:
            print(f'Failed to get metadata for {loc} after three attempts, skipping...')
            return False

        return metadata


    def find_commentary_tracks(self, metadata, data):
        version_number = -1
        for version in metadata['Media']:
            version_number += 1
            if len(version['Part']) < 1 or 'Stream' not in version['Part'][0]:
                continue # Bad file, no streams/parts?

            for stream in version['Part'][0]['Stream']: # Just look at first part, as all parts must be identical
                if stream['streamType'] != 2:
                    continue
                track_name = stream['title' if 'title' in stream else ('displayTitle' if 'displayTitle' in stream else 'extendedDisplayTitle')]
                track_language = stream['languageCode'] if 'languageCode' in stream else 'unknown'
                track_channels = int(stream['channels']) if 'channels' in stream else 0
                data['all_tracks'][version_number].append({ 'name' : track_name, 'lang' : track_language, 'channels' : track_channels })
                for search in ['title', 'displayTitle', 'extendedDisplayTitle']:
                    if search not in stream:
                        continue
                    title = stream[search].lower()
                    found_commentary = False
                    for keyword in self.keywords:
                        if title.find(keyword) != -1:
                            found_commentary = True
                            break
                    if not found_commentary:
                        continue

                    data['commentary'].append(stream[search])
                    break



    def get_collections(self, metadata):
        """Finds all the collections the given video currently belongs to, and returns them as a list"""

        if 'Collection' not in metadata:
            return []

        collections = []
        for collection in metadata['Collection']:
            collections.append(collection['tag'])
        return collections


    def postprocess(self):
        """Processes the results of the scan

        Prints out all commentary tracks and adds the media to the commentary collection if it's not already in it
        """

        lib_type = 'Movie(s)' if self.section_type == 'movie' else 'Episode(s)'
        commentary_count = len([item for item in self.commentaries if len(self.commentaries[item]['commentary']) > 0])
        print(f'\nFound {commentary_count} {lib_type.lower()} with commentaries')
        added = []
        print()
        print(f'{lib_type} already in "{self.collection_name}":')
        print(f'===========================================')
        for item in self.commentaries.keys():
            tracks = self.commentaries[item]['commentary']
            if len(tracks) == 0:
                continue

            collections = self.commentaries[item]['collections']
            if self.collection_name in collections:
                print(f'{item} ({len(tracks)} commentary track{"s" if len(tracks) > 1 else ""})')
            else:
                self.add_to_commentary_collection(self.commentaries[item]['id'], collections)
                collections.append(self.collection_name)
                added.append({ 'title': item, 'tracks' : len(tracks) })
                if self.verbose:
                    for track in tracks:
                        print(f'\t{track}')
        print(f'\nAdded {len(added)} new {lib_type.lower()} to collection:')
        print(f'===========================================')
        for item in added:
            print(f'{item["title"]} ({item["tracks"]} commentary track{"s" if item["tracks"] > 1 else ""})')
        print()

        self.show_more_tracks()



    def add_to_commentary_collection(self, metadata_id, collections):
        """Sends the request to the Plex server to add the given item to the collection"""

        lib_type = 1 if self.section_type == 'movie' else 4
        url = f'{self.host}/library/sections/{self.section_id}/all?type={lib_type}&id={metadata_id}'
        for index in range(len(collections)):
            url += f'&collection%5B{index}%5D.tag.tag={urllib.parse.quote(collections[index])}'
        url += f'&collection%5B{len(collections)}%5D.tag.tag={urllib.parse.quote(self.collection_name)}'
        url += f'&X-Plex-Token={self.token}'
        options = requests.options(url)
        put = requests.put(url)
        put.close() # Are the close statements necessary?
        options.close()
        return


    def show_more_tracks(self):
        """
        Optionally shows the user additional items that have not been
        added to the collection, but contain 2+ English audio tracks
        """

        lib_type = 'movie' if self.section_type == 'movie' else 'episode'
        show_more = self.get_yes_no(f'Show additional {lib_type}s with 2+ English audio tracks')
        if not show_more:
            return

        limit_2ch = self.get_yes_no(f'Only show additional {lib_type}s with a 2 channel track (most common commentary format)')
        interactive = self.get_yes_no(f'Interactively add additional {lib_type}s to collection')
        track_ignored = False
        if interactive:
            track_ignored = self.get_yes_no('Use and update ignore list')
        ignored = {} # Dict for O(n) access
        if track_ignored and os.path.exists(self.adjacent_file('ignore.txt')):
            with open(self.adjacent_file('ignore.txt')) as f:
                lines = f.readlines()
                for line in lines:
                    ignored[line.strip()] = True

        add_queue = []
        eligible_tracks = 0
        ignored_count = 0
        for item in self.commentaries.keys():
            versions = self.commentaries[item]['all_tracks']
            version = -1
            for tracks in versions:
                version += 1
                if len(tracks) < 2:
                    continue
                if self.collection_name in self.commentaries[item]['collections']:
                    continue
                if track_ignored and self.commentaries[item]['id'] in ignored:
                    continue

                # Also consider unknown languages
                eng_tracks = len([track for track in tracks if track['lang'] in ['eng', 'unknown']])
                two_channel_check = True
                if limit_2ch:
                    two_channel_check = len([track for track in tracks if track['channels'] == 2])

                if eng_tracks > 1 and two_channel_check:
                    eligible_tracks += 1
                    print(f'{item}{" (version " + str(version + 1) + ")" if len(versions) > 1 else ""} has {eng_tracks} English tracks ({len(tracks)} total)')
                    for track in tracks:
                        if self.verbose or track['lang'] in ['eng', 'unknown']:
                            print(f'\t{track["name"]} ({track["lang"]}) - {track["channels"]} channels')
                    if interactive and self.get_yes_no(f'\nAdd "{item}" to "{self.collection_name}"'):
                        add_queue.append(item)
                        print(f'Adding {item} to append queue\n')
                    elif track_ignored:
                        ignored[self.commentaries[item]['id']] = True
                        ignored_count += 1
                    print()
        
        if ignored_count > 1:
            print(f'Adding {ignored_count} {lib_type}{"" if ignored_count == 1 else "s"} to the ignore list')
            with open(self.adjacent_file('ignore.txt'), 'w+') as f:
                f.writelines([ignore + '\n' for ignore in ignored])

        if eligible_tracks == 0:
            print("Didn't find anything to add")

        if len(add_queue) == 0:
            return
        
        print(f'\nAdding {len(add_queue)} {lib_type}(s) to "{self.collection_name}')
        for item in add_queue:
            self.add_to_commentary_collection(self.commentaries[item]['id'], self.commentaries[item]['collections'])
            print(f'Added "{item}" to "{self.collection_name}')


    def get_json_response(self, url, params={}):
        """Returns the JSON response from the given URL"""
        response = requests.get(self.url(url, params), headers={ 'Accept' : 'application/json' })
        if response.status_code != 200:
            data = None
        else:
            try:
                data = json.loads(response.content)['MediaContainer']
            except:
                print('ERROR: Unexpected JSON response:\n')
                print(response.content)
                print()
                data = None

        response.close()
        return data


    def url(self, base, params={}):
        """Builds and returns a url given a base and optional parameters. Parameter values are URL encoded"""
        real_url = f'{self.host}{base}'
        sep = '?'
        for key, value in params.items():
            real_url += f'{sep}{key}={parse.quote(value)}'
            sep = '&'

        return f'{real_url}{sep}X-Plex-Token={self.token}'


    def get_yes_no(self, prompt):
        """Prompt the user for a yes/no response, continuing to show the prompt until a value that starts with 'y' or 'n' is entered"""

        while True:
            response = input(f'{prompt} (y/n)? ')
            ch = response.lower()[0] if len(response) > 0 else 'x'
            if ch in ['y', 'n']:
                return ch == 'y'

    def adjacent_file(self, filename):
        """Returns the file path for a file that is in the same directory as this script"""

        return os.path.realpath(os.path.join(os.getcwd(), os.path.dirname(__file__))) + os.sep + filename

if __name__ == '__main__':
    runner = CommentaryCollection()
    runner.run()