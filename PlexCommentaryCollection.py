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
        self.host = CommentaryCollection.get_config_value(config, 'host', 'http://localhost:32400')
        self.section = CommentaryCollection.get_config_value(config, 'library_section', '1')
        self.collection_name = CommentaryCollection.get_config_value(config, 'collection_name', 'Commentary Collection')
        self.keywords = [keyword.lower() for keyword in CommentaryCollection.get_config_value(config, 'keywords', ['commentary'])]
        self.valid = True


    def get_config_value(config, key, default):
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
        for media in video.findall('Media'):
            tracks = self.find_commentary_tracks(media)
            if (len(tracks) != 0):
                if movie_title not in self.commentaries:
                    self.commentaries[movie_title] = { 'collections': [], 'commentary': [], 'id': metadata_id }
                self.commentaries[movie_title]['commentary'] = tracks

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


    def find_commentary_tracks(self, media):
        """Searches the audio tracks of the given media for the keywords specified in the config file

        Returns a list of commentary tracks that were found
        """

        commentary_tracks = []
        audio_streams = media.findall('Part/Stream[@streamType="2"]')
        for stream in audio_streams:
            for search in ['title', 'extendedDisplayTitle']:
                if search not in stream.attrib:
                    continue

                title = stream.attrib[search].lower()
                if title.find('commentary') == -1:
                    continue

                commentary_tracks.append(stream.attrib[search])
                break
        return commentary_tracks


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

        print(f'\nFound {len(self.commentaries)} movie{"" if len(self.commentaries) == 1 else "s"} with commentaries')
        for movie in self.commentaries.keys():
            tracks = self.commentaries[movie]['commentary']
            collections = self.commentaries[movie]['collections']
            print(f'{movie} has {len(tracks)} commentary track{"s" if len(tracks) > 1 else ""}', end='')
            if self.collection_name in collections:
                print(f' and is already in "{self.collection_name}"')
            else:
                print(f', adding to {self.collection_name}')
                self.add_to_commentary_collection(self.commentaries[movie]['id'], collections)
            for track in tracks:
                print(f'\t{track}')


    def add_to_commentary_collection(self, metadata_id, collections):
        """Sends the request to the Plex server to add the given item to the collection"""

        url = f'{self.host}/library/sections/{self.section}/all?type=1&id={metadata_id}'
        for index in range(len(collections)):
            url += f'&collection%5B{index}%5D.tag.tag={urllib.parse.quote(collections[index])}'
        url += f'&collection%5B{len(collections)}%5D.tag.tag={urllib.parse.quote(self.collection_name)}'
        url += f'&X-Plex-Token={self.token}'
        options = requests.options(url)
        put = requests.put(url)

        return

if __name__ == '__main__':
    runner = CommentaryCollection()
    runner.run()