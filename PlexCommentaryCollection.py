import math
import os
import requests
import time
import urllib
import xml.etree.ElementTree as ET
import yaml


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
        config_file = os.path.realpath(os.path.join(os.getcwd(), os.path.dirname(__file__))) + os.sep + 'config.yml'
        if not os.path.exists(config_file):
            print('Could not find config.yml! Make sure it\'s in the same directory as this script')
            return

        with open(config_file) as f:
            config = yaml.load(f, Loader=yaml.SafeLoader)

        if 'token' not in config:
            print('Plex token not found in config! Aborting...')
            return

        self.token = config['token']
        self.host = self.get_config_value(config, 'host', 'http://localhost:32400')
        self.section = self.get_config_value(config, 'library_section', '1')
        self.collection_name = self.get_config_value(config, 'collection_name', 'Commentary Collection')
        self.keywords = [keyword.lower() for keyword in self.get_config_value(config, 'keywords', ['commentary'])]
        self.verbose = self.get_config_value(config, 'verbose', False)
        self.valid = True


    def get_config_value(self, config, key, default):
        """Returns a value from the given config, or the default value if not present"""

        if key not in config:
            print(f'${key} not found in config, defaulting to "{default}"')
            return default
        return config[key]


    def run(self):
        """Kick off the processing"""

        if not self.valid:
            return

        root = self.get_all_items()
        movie_count = len(root)
        print(f'Found {movie_count} movies to parse')
        processed = 0
        start = time.time()
        update_interval = 2
        next_update = update_interval
        for movie in root:
            processed += 1

            self.process_movie(movie)

            end = time.time()
            if (math.floor(end - start) >= next_update):
                next_update += update_interval
                print(f'Processed {processed} of {movie_count} ({((processed / movie_count) * 100):.2f}%) in {(end - start):.1f} seconds')

        print(f'\nDone! Processed {processed} movie{"" if movie_count == 1 else "s"} in {time.time() - start:.2f} seconds')
        self.postprocess()


    def get_all_items(self):
        """Returns all the media items from the library"""

        url = f'{self.host}/library/sections/{self.section}/all?type=1&X-Plex-Token={self.token}'
        response = requests.get(url)
        data = ET.fromstring(response.content)
        response.close()
        return data


    def process_movie(self, movie):
        """Processes a single movie, adding it to the commentaries dictionary if commentary tracks are found"""

        metadata = ET.fromstring(self.get_metadata(movie.attrib['key']))
        metadata_id = movie.attrib['key']
        metadata_id = metadata_id[metadata_id.rfind('/') + 1:]
        if not metadata:
            return

        video = metadata.find('Video')
        movie_title = video.attrib['title']
        self.commentaries[movie_title] = { 'collections': [], 'commentary': [], 'id': metadata_id, 'all_tracks' : [] }
        for media in video.findall('Media'):
            self.find_commentary_tracks(media, self.commentaries[movie_title])

        if movie_title in self.commentaries:
            self.commentaries[movie_title]['collections'] = self.get_collections(video)


    def get_metadata(self, loc):
        """Retrieves the metadata for the item specified by loc"""

        url = f'{self.host}{loc}?X-Plex-Token={self.token}'
        attempts = 0
        while attempts < 3:
            attempts += 1
            try:
                metadata_request = requests.get(url)
                break
            except:
                if attempts != 3:
                    print(f'Failed to get metadata for {loc}, retrying...')
                    time.sleep(1) # This could be a network hiccup, wait for a second before retrying

        if attempts == 3:
            print(f'Failed to get metadata for {loc} after three attempts, skipping...')
            return False

        content = metadata_request.content
        metadata_request.close()
        return content


    def find_commentary_tracks(self, media, data):
        """Searches the audio tracks of the given media for the keywords specified in the config file

        Returns a list of commentary tracks that were found
        """

        audio_streams = media.findall('Part/Stream[@streamType="2"]')
        for stream in audio_streams:
            track_name = stream.attrib['title' if 'title' in stream.attrib else ('displayTitle' if 'displayTitle' in stream.attrib else 'extendedDisplayTitle')]
            track_language = stream.attrib['languageCode'] if 'languageCode' in stream.attrib else 'unknown'
            track_channels = int(stream.attrib['channels']) if 'channels' in stream.attrib else 0
            data['all_tracks'].append({ 'name' : track_name, 'lang' : track_language, 'channels' : track_channels })
            for search in ['title', 'displayTitle', 'extendedDisplayTitle']:
                if search not in stream.attrib:
                    continue

                title = stream.attrib[search].lower()
                found_commentary = False
                for keyword in self.keywords:
                    if title.find(keyword) != -1:
                        found_commentary = True
                        break

                if not found_commentary:
                    continue

                data['commentary'].append(stream.attrib[search])
                break


    def get_collections(self, video):
        """Finds all the collections the given video currently belongs to, and returns them as a list"""

        collections = []
        for collection in video.findall('Collection'):
            collections.append(collection.attrib['tag'])
        return collections


    def postprocess(self):
        """Processes the results of the scan

        Prints out all commentary tracks and adds the media to the commentary collection if it's not already in it
        """

        commentary_count = len([movie for movie in self.commentaries if len(self.commentaries[movie]['commentary']) > 0])
        print(f'\nFound {commentary_count} movie{"" if commentary_count == 1 else "s"} with commentaries')
        added = []
        for movie in self.commentaries.keys():
            tracks = self.commentaries[movie]['commentary']
            if len(tracks) == 0:
                continue

            collections = self.commentaries[movie]['collections']
            print(f'{movie} has {len(tracks)} commentary track{"s" if len(tracks) > 1 else ""}', end='')
            if self.collection_name in collections:
                print(f' and is already in "{self.collection_name}"')
            else:
                print(f', adding to {self.collection_name}')
                self.add_to_commentary_collection(self.commentaries[movie]['id'], collections)
                collections.append(self.collection_name)
                added.append(movie)
            if self.verbose:
                for track in tracks:
                    print(f'\t{track}')
        print(f'\nAdded {len(added)} movies to collection')
        if self.verbose:
            for movie in added:
                print(f'\t{movie}')

        self.show_more_tracks()



    def add_to_commentary_collection(self, metadata_id, collections):
        """Sends the request to the Plex server to add the given item to the collection"""

        url = f'{self.host}/library/sections/{self.section}/all?type=1&id={metadata_id}'
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
        Optionally shows the user additional movies that have not been
        added to the collection, but contain 2+ English audio tracks
        """

        show_more = self.get_yes_no('Show additional movies with 2+ English audio tracks')
        if not show_more:
            return

        limit_2ch = self.get_yes_no('Only show additional movies with a 2 channel track (most common commentary format)')
        for movie in self.commentaries.keys():
            tracks = self.commentaries[movie]['all_tracks']
            if len(tracks) < 2:
                continue
            if self.collection_name in self.commentaries[movie]['collections']:
                continue

            # Also consider unknown languages
            eng_tracks = len([track for track in tracks if track['lang'] in ['eng', 'unknown']])
            two_channel_check = True
            if limit_2ch:
                two_channel_check = len([track for track in tracks if track['channels'] == 2])

            if eng_tracks > 1 and two_channel_check:
                print(f'{movie} has {eng_tracks} English tracks ({len(tracks)} total)')
                for track in tracks:
                    if self.verbose or track['lang'] in ['eng', 'unknown']:
                        print(f'\t{track["name"]} ({track["lang"]}) - {track["channels"]} channels')


    def get_yes_no(self, prompt):
        """Prompt the user for a yes/no response, continuing to show the prompt until a value that starts with 'y' or 'n' is entered"""

        while True:
            response = input(f'{prompt} (y/n)? ')
            ch = response.lower()[0] if len(response) > 0 else 'x'
            if ch in ['y', 'n']:
                return ch == 'y'

if __name__ == '__main__':
    runner = CommentaryCollection()
    runner.run()