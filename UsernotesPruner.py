import logging
import logging.config

import praw

import usernotes


def is_ban_note(user_note):
    return 'ban' in user_note['n'].lower()


def prune_very_old_notes(username, entry, cutoff_days):
    user_notes_after_pruning_very_old_entries = []
    for user_note in entry['ns']:
        age_of_user_note = usernotes.get_age_of_user_note(user_note)
        note_prunable = False
        if age_of_user_note.days > cutoff_days:
            if not is_ban_note(user_note):
                logging.info('pruned very old note from {0} days ago for /u/{1}\t{2}'.format(
                    age_of_user_note.days, username, user_note['n'].encode('UTF-8', 'ignore')))
                note_prunable = True

        if not note_prunable:
            user_notes_after_pruning_very_old_entries.append(user_note)

    entry['ns'] = user_notes_after_pruning_very_old_entries


def check_user_prunable(username, entry, cutoff_days):
    user_notes = entry['ns']
    if len(user_notes) == 0:
        logging.info('pruned /u/{0} without any notes'.format(username))
        return True
    elif len(user_notes) == 1:
        only_user_note = user_notes[0]
        age_of_only_user_note = usernotes.get_age_of_user_note(only_user_note)
        if age_of_only_user_note.days > cutoff_days and not is_ban_note(only_user_note):
            logging.info('pruned only user note from {0} days ago for /u/{1}\t{2}'.format(
                age_of_only_user_note.days, username, only_user_note['n'].encode('UTF-8', 'ignore')))
            return True

    return False


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
        cutoff_days_for_users_with_only_one_note = 25
        cutoff_days_for_all_notes = 50

        logging.info("Checking users with notes older than {0} days or a single note older than {1} days"
                     .format(cutoff_days_for_all_notes, cutoff_days_for_users_with_only_one_note))

        usernotes_wrapper = usernotes.load_from_wiki_page(r, subreddit_name)
        users = usernotes_wrapper.decoded_users_blob_json
        logging.info('users before pruning: {0}'.format(len(users)))
        for username, entry in users.items():
            prune_very_old_notes(username, entry, cutoff_days_for_all_notes)
            if check_user_prunable(username, entry, cutoff_days_for_users_with_only_one_note):
                del users[username]
        logging.info('users after pruning: {0}'.format(len(users)))

        wiki_page_edit_reason = 'User notes pruning: ' + \
            'notes older than {0} days '.format(cutoff_days_for_all_notes) + \
            'and single note users where note is older than {0} days'.format(cutoff_days_for_users_with_only_one_note)
        usernotes.save_to_wiki_page(r, usernotes_wrapper, wiki_page_edit_reason, subreddit_name)

    except Exception as exception:
        logging.exception(exception)


if __name__ == '__main__':
    main()
