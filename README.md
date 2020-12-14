# Plex Commentary Collection

Plex Commentary Collection is a script to create a Plex collection for items that have commentary audio tracks. It does so by scanning every item in a specified library, iterating over all of its audio tracks, and adding it to a specified collection if the track names include specific keywords, such as "commentary".
~
There's very little hardening against invalid configuration values, so it's best to ensure they're correct before running the script

## Usage
`python PlexCommentaryCollection.py`

## Configuration
Configuration values are pretty self-explanatory, but for completeness they're outlined below:

* `host`: The host of the Plex server. Defaults to http://localhost:32400
* `library_section`: The id of the library to scan. Defaults to 1
* `token`: Your Plex token. No default, must be provided
* `collection_name`: The name of the collection to add items to. Defaults to "Commentary Collection"
* `keywords`: A list of keywords to look for in audio stream titles. Defaults to `['commentary']`