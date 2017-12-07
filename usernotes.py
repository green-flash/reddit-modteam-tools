import base64
import json
import logging
import zlib
from datetime import datetime

USERS_BLOB_PROPERTY_NAME = 'blob'
USERNOTES_WIKI_PAGE_NAME = 'usernotes'


def get_age_of_user_note(user_note):
    """Extract the age of the given usernote as a timedelta object"""
    datetime_of_user_note = datetime.utcfromtimestamp(user_note['t'])
    age_of_user_note = datetime.utcnow() - datetime_of_user_note
    return age_of_user_note


def get_link_to_referenced_comment(subreddit_name, user_note):
    """Extracts the id of the comment referenced by the usernote and formats it as a reddit-internal link"""
    link_code_segments = user_note['l'].split(',')
    if len(link_code_segments) == 3:
        submission_id = link_code_segments[1]
        comment_id = link_code_segments[2]
        return '/r/{0}/comments/{1}/x/{2}/?context=3'.format(subreddit_name, submission_id, comment_id)
    else:
        return None


def get_id_of_referenced_submission(user_note):
    """Extracts the id of the submission referenced by the usernote"""
    link_code_segments = user_note['l'].split(',')
    if len(link_code_segments) > 1:
        return link_code_segments[1]
    else:
        return None


def get_decompressed_users_blob(compressed_usernotes_json):
    """Return the decoded and decompressed version of the users blob from the given usernotes json"""
    decoded_users_blob = base64.b64decode(compressed_usernotes_json[USERS_BLOB_PROPERTY_NAME])
    decompressed_users_blob = zlib.decompress(decoded_users_blob, zlib.MAX_WBITS)
    return json.loads(decompressed_users_blob)


def recompress_users_blob(modified_users_json):
    """Recompress and re-encode the given users to a blob for storage"""
    modified_users_json_dump = json.dumps(modified_users_json, separators=(',', ':'))
    recompressed = zlib.compress(modified_users_json_dump, 9)
    return base64.b64encode(recompressed)


def load_from_wiki_page(r, subreddit_name):
    """Load the usernotes json data from the usernotes wiki page of the given subreddit"""
    logging.info('loading usernotes from subreddit {0}'.format(subreddit_name))
    usernotes_wiki_page = r.subreddit(subreddit_name).wiki[USERNOTES_WIKI_PAGE_NAME]
    logging.info('done loading usernotes from subreddit {0}'.format(subreddit_name))

    logging.info('loading usernotes wikipage data as json ...')
    json_data = json.loads(usernotes_wiki_page.content_md)
    logging.info('done loading usernotes wikipage data as json')

    logging.info('decompressing users blob from usernotes json ...')
    decompressed_users_blob_json = get_decompressed_users_blob(json_data)
    logging.info('done decompressing users blob from usernotes json')
    return UsernotesWrapper(json_data, decompressed_users_blob_json)


def save_to_wiki_page(r, usernotes, edit_reason, subreddit_name):
    """Save the usernotes json data to the usernotes wiki page of the given subreddit"""
    logging.info('recompressing users blob for storing usernotes json ...')
    json_data = usernotes.compressed_json_data
    json_data[USERS_BLOB_PROPERTY_NAME] = recompress_users_blob(usernotes.decoded_users_blob_json)
    logging.info('done recompressing users blob for storing usernotes json')
    logging.info('dumping usernotes json to string representation ...')
    json_dump = json.dumps(json_data, separators=(',', ':'))
    logging.info('done dumping usernotes json to string representation')
    logging.info('writing usernotes to subreddit {0}'.format(subreddit_name))
    r.subreddit(subreddit_name).wiki[USERNOTES_WIKI_PAGE_NAME].edit(json_dump, edit_reason)
    logging.info('done writing usernotes to subreddit {0}'.format(subreddit_name))


class UsernotesWrapper:
    """Wrapper for toolbox usernotes data, contains the original compressed json data and the decoded users blob"""

    def __init__(self, compressed_json_data, decoded_users_blob_json):
        self.compressed_json_data = compressed_json_data
        self.decoded_users_blob_json = decoded_users_blob_json
