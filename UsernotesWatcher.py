import logging
import logging.config
import re
from datetime import datetime

import praw

import usernotes

LOOKBACK_PERIOD_IN_MINUTES = 15
NEW_USER_THRESHOLD_IN_DAYS = 30
NUMBER_OF_NOTES_TO_TRIGGER_ALERT = 4

INSTABAN_NOTE_TERMS = ['kill yourself', 'kys', 'hope you die', 'vile', 'very out of date', 'vood']

PERSONAL_ATTACK_NOTES = ['pa', 'sha']

usernotes_link_regex = re.compile('/x/([^/]+)/', re.IGNORECASE)
submission_link_regex = re.compile('/comments/([^/]+)/\)', re.IGNORECASE)
message_link_regex = re.compile('/message/messages/([^\)]+)', re.IGNORECASE)


def is_instaban_note(user_note):
    return is_instaban_note_text(user_note['n'])


def is_instaban_note_text(user_note_text):
    return any(instaban_term in user_note_text.lower() for instaban_term in INSTABAN_NOTE_TERMS)


def is_personal_attack_note_text(user_note_text):
    return user_note_text.lower() in PERSONAL_ATTACK_NOTES


def is_ban_related_note(user_note):
    return 'ban' in user_note['n'].lower()


def get_redditor_safe(username):
    logging.info('Fetching profile of user {0} ...'.format(username))
    redditor = r.redditor(username)
    if hasattr(redditor, 'id'):
        return redditor
    elif hasattr(redditor, 'is_suspended'):
        logging.info('User {0} appears to have been suspended.'.format(username))
        return None
    else:
        logging.info('User {0} appears to have been shadowbanned or has deleted their account.'.format(username))
        return None


def is_user_new(username, cutoff_days):
    logging.debug('checking if /u/{0} with a user note is a new account'.format(username))
    redditor = get_redditor_safe(username)
    if redditor is not None:
        account_age = datetime.utcnow() - datetime.utcfromtimestamp(redditor.created_utc)
        if account_age.days < cutoff_days:
            logging.info('found new user /u/{0} with notes, account created {1} days ago'.format(username,
                                                                                                 account_age.days))
            return True

    return False


def collect_notes_after_last_ban(notes_by_most_recent_first, subreddit_name, mods):
    notes_after_last_ban = []
    note_texts_after_last_ban = []
    for user_note in notes_by_most_recent_first:
        if is_ban_related_note(user_note):
            break
        else:
            link_ids = user_note['l'].split(',')
            user_note_text_ascii = user_note['n'].encode('ascii', 'ignore')
            link_start = '[{0}](/r/{1}'.format(user_note_text_ascii, subreddit_name)
            age_of_user_note = usernotes.get_age_of_user_note(user_note)

            mod_name = mods[user_note['m']]
            if age_of_user_note.days > 0:
                additional_info = ' ({0} days ago by /u/{1})'.format(age_of_user_note.days, mod_name)
            elif age_of_user_note.seconds > 3600:
                additional_info = ' ({0} hours ago by /u/{1})'.format(age_of_user_note.seconds // 3600, mod_name)
            else:
                additional_info = ' ({0} minutes ago by /u/{1})'.format(age_of_user_note.seconds // 60, mod_name)

            link = None
            if len(link_ids) == 2 and link_ids[0] == 'm':
                link = link_start + '/message/messages/{0})'.format(link_ids[1]) + additional_info
            elif len(link_ids) == 2:
                link = link_start + '/comments/{0}/)'.format(link_ids[1]) + additional_info
            elif len(link_ids) == 3:
                link = link_start + '/comments/{0}/x/{1}/?context=3)'.format(link_ids[1], link_ids[2]) + additional_info

            notes_after_last_ban.append(link)
            note_texts_after_last_ban.append(user_note_text_ascii)

    if len(note_texts_after_last_ban) == 1 and check_single_note_ignorable(note_texts_after_last_ban[0],
                                                                           notes_after_last_ban[0]):
        return []
    else:
        return notes_after_last_ban


def check_single_note_ignorable(usernote_text, usernote_link):
    is_personal_attack_note = is_personal_attack_note_text(usernote_text)
    is_submission_note = 'context' not in usernote_link
    return is_personal_attack_note or (is_submission_note and not is_instaban_note_text(usernote_text))


def check_user_bannable(username, entry, subreddit_name, recently_processed_links, mods):
    len_notes = len(entry['ns'])
    notes_by_most_recent_first = sorted(entry['ns'], key=lambda x: x['t'], reverse=True)
    age_of_most_recent_user_note = usernotes.get_age_of_user_note(notes_by_most_recent_first[0])

    if (age_of_most_recent_user_note.days > 0 or
            age_of_most_recent_user_note.seconds // 60 > LOOKBACK_PERIOD_IN_MINUTES):
        return None

    link_ids_of_most_recent_note = notes_by_most_recent_first[0]['l'].split(',')
    if (len(link_ids_of_most_recent_note) == 3 and link_ids_of_most_recent_note[2] in recently_processed_links) \
            or (len(link_ids_of_most_recent_note) == 2 and link_ids_of_most_recent_note[1] in recently_processed_links):
        return None

    if is_instaban_note(notes_by_most_recent_first[0]) or is_user_new(username, cutoff_days=NEW_USER_THRESHOLD_IN_DAYS):
        notes_after_last_ban = collect_notes_after_last_ban(notes_by_most_recent_first, subreddit_name, mods)
        if len(notes_after_last_ban) > 0:
            return notes_after_last_ban

    if len_notes >= NUMBER_OF_NOTES_TO_TRIGGER_ALERT:
        notes_after_last_ban = collect_notes_after_last_ban(notes_by_most_recent_first, subreddit_name, mods)
        if len(notes_after_last_ban) >= NUMBER_OF_NOTES_TO_TRIGGER_ALERT:
            return notes_after_last_ban

    return None


def determine_recently_processed_links():
    recently_processed_links = set()
    for sent_message in r.inbox.sent(limit=50):
        if sent_message.parent_id is None and 'Possible candidates for a ban' in sent_message.subject:
            for usernote_link in re.findall(usernotes_link_regex, sent_message.body):
                recently_processed_links.add(usernote_link)
            for submission_link in re.findall(submission_link_regex, sent_message.body):
                recently_processed_links.add(submission_link)
            for message_link in re.findall(message_link_regex, sent_message.body):
                recently_processed_links.add(message_link)
    logging.debug('Recently processed usernote links to be ignored: {0}'.format(recently_processed_links))
    return recently_processed_links


def determine_recent_ban_notes(subreddit):
    recent_ban_notes = {}
    for ban_info in subreddit.banned(limit=20):
        banned_user_name = ban_info.name
        recent_ban_notes[banned_user_name] = ban_info.note
    return recent_ban_notes


def send_bannable_user_alert(subreddit, bannable_users):
    bannable_users_as_string = ', '.join(str(user.encode('ascii')) for user in bannable_users.keys())
    subject = 'Possible candidates for a ban: {0}'.format(bannable_users_as_string
                                                          if len(bannable_users_as_string) < 60
                                                          else bannable_users_as_string[:60] + ' ... ')
    message = 'The following users might qualify for a ban ' \
              'or have already been banned and are just missing a \"banned\" usernote:\n\n'

    for user, qualifying_notes in bannable_users.items():
        message += '* /u/{0}\n'.format(user)
        for qualifying_note in qualifying_notes:
            message += ' * {0}\n'.format(qualifying_note)

    message += '\n^(If there are less than {0} usernotes, that means this is either a user account ' \
               'younger than {1} days or an instaban offense.)'.format(NUMBER_OF_NOTES_TO_TRIGGER_ALERT,
                                                                       NEW_USER_THRESHOLD_IN_DAYS)

    subreddit.message(subject, message)
    logging.info('sent following message for possible bans: {0}'.format(message))


# global reddit session
r = None


def main():
    global r

    logging.config.fileConfig('logging.cfg')
    subreddit_name = 'my_subreddit'
    r = praw.Reddit(username="my_username",
                    password="my_password",
                    user_agent="my_useragent",
                    client_id="my_client_id",
                    client_secret="my_client_secret")
    r.config.decode_html_entities = True

    try:
        recently_processed_links = determine_recently_processed_links()
        subreddit = r.subreddit(subreddit_name)
        recent_ban_notes = determine_recent_ban_notes(subreddit)

        usernotes_wrapper = usernotes.load_from_wiki_page(r, subreddit_name)
        json_data = usernotes_wrapper.compressed_json_data

        mods = json_data['constants']['users']
        users = usernotes_wrapper.decoded_users_blob_json

        logging.info('checking users for possible ban')
        bannable_users = {}
        for username, entry in users.items():
            if username not in recent_ban_notes:
                qualifying_notes = check_user_bannable(username, entry, subreddit_name, recently_processed_links, mods)
                if qualifying_notes is not None:
                    bannable_users[username] = qualifying_notes

        if len(bannable_users) > 0:
            send_bannable_user_alert(subreddit, bannable_users)

        logging.info('done checking users for possible ban')

    except Exception as exception:
        logging.exception(exception)


if __name__ == '__main__':
    main()
