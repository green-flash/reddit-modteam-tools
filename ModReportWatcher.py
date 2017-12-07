import json
import logging
import logging.config
import time
from collections import defaultdict

import praw
from praw.models import Submission

import usernotes

REMOVAL_FLAIR_CSS_CLASS = 'normal'

TRUSTED_REPORTER_SCORE_LIMIT = 100

rule_linkflair_mapping = {'US Internal News or Politics': 'US Internal',
                          'Editorialized or Misleading Title': 'Editorialized Title',
                          'Feature story': 'Feature Story',
                          'Editorial, Opinion, or Analysis': 'Opinion/Analysis',
                          'Not in English': 'Not in English',
                          'Image, Video or Audio Clip': 'No Images/Videos',
                          'Out of Date': 'Out of Date'}

rule_note_mapping = {'US Internal News or Politics': 'us',
                     'Editorialized or Misleading Title': 'edt',
                     'Feature story': 'feat',
                     'Editorial, Opinion, or Analysis': 'op/an',
                     'Not in English': 'non-eng',
                     'Image, Video or Audio Clip': 'img/vid',
                     'Bigotry or Other Offensive Content': 'bigotry',
                     'Personal Attack': 'pa',
                     'Memes, Gifs, unlabeled NSFW images': 'meme',
                     'Out of Date': 'ood'}


def is_submission_moderator(moderator):
    return 'all' in moderator.mod_permissions or 'flair' in moderator.mod_permissions


def is_comment_moderator(moderator):
    return 'posts' in moderator.mod_permissions and 'flair' not in moderator.mod_permissions


def note_for_link_id_exists(usernotes_entry, link_id):
    for note in usernotes_entry['ns']:
        if usernotes.get_age_of_user_note(note).days < 2 and usernotes.get_id_of_referenced_submission(note) == link_id:
            return True
    return False


def create_usernote(note_text, mod_name, post_id, comment_id, usernotes_constants):
    if mod_name not in usernotes_constants['users']:
        usernotes_constants['users'].append(mod_name)
    mod_index = usernotes_constants['users'].index(mod_name)
    warn_type_index = usernotes_constants['warnings'].index('abusewarn')
    current_time_in_sec = time.time()
    link_info = 'l,{0}'.format(post_id) if comment_id is None else 'l,{0},{1}'.format(post_id, comment_id)
    usernote = {'t': int(current_time_in_sec),
                'm': mod_index,
                'n': note_text,
                'w': warn_type_index,
                'l': link_info}
    return usernote


def add_usernote_for_rule_violation(user_name, report_reason, reporter_name, post_id, comment_id, users, constants):
    note_text = 'vile' if is_vile_report(report_reason, reporter_name) else rule_note_mapping[report_reason]
    new_usernote = create_usernote(note_text, reporter_name, post_id, comment_id, constants)
    if user_name not in users.keys():
        users[user_name] = {'ns': []}
    users[user_name]['ns'].insert(0, new_usernote)


def is_mod_rule_report(report_reason, reporter_name):
    return reporter_name != 'AutoModerator' and report_reason is not None and report_reason in rule_note_mapping.keys()


def is_spam_report(report_reason, reporter_name):
    return reporter_name != 'AutoModerator' and (report_reason is None or report_reason.lower() == 'this is spam')


def is_vile_report(report_reason, reporter_name):
    return reporter_name != 'AutoModerator' and report_reason is not None and report_reason.lower() == 'vile'


def is_mod_rule_or_vile_report(report_reason, reporter_name):
    return is_mod_rule_report(report_reason, reporter_name) or is_vile_report(report_reason, reporter_name)


def is_mod_rule_or_spam_or_vile_report(report):
    return is_mod_rule_report(report[0], report[1]) \
           or is_spam_report(report[0], report[1]) \
           or is_vile_report(report[0], report[1])


def has_mod_rule_reports(queue_item):
    return len(filter(is_mod_rule_or_spam_or_vile_report, queue_item.mod_reports)) > 0


def process_rule_violation_report(item, subreddit, users, constants, submission_mods, comment_mods):
    item_author = item.author.name if item.author is not None else None
    for report in item.mod_reports:
        is_submission_report = type(item) is Submission
        report_reason = report[0]
        reporter_name = report[1]
        is_no_submission_moderator = reporter_name not in submission_mods
        is_trusted_reporter = reporter_name not in submission_mods and reporter_name not in comment_mods

        if item_author in submission_mods:
            logging.info('skipping report on item from submission mod {0} by {1}'.format(item_author, reporter_name))
            continue

        if is_spam_report(report_reason, reporter_name):
            if item.score >= 2 or (not is_submission_report and len(item.replies) > 0):
                logging.info('skipping spam report on item from {0} by {1}'.format(item_author, reporter_name))
            else:
                item.mod.remove()
                logging.info("removed item from {0} with spam report by {1}".format(item_author, reporter_name))
                if is_submission_report:
                    logging.info('writing spam usernote for user {0} and post id {1}'.format(item_author, item.id))
                    add_usernote_for_rule_violation(item_author, 'spam', reporter_name, item.id, None, users, constants)
                return reporter_name

        if is_no_submission_moderator and is_submission_report:
            logging.info('skipping submission report on item from {0} by {1}'.format(item_author, reporter_name))
            continue
        if is_trusted_reporter and item.score > TRUSTED_REPORTER_SCORE_LIMIT:
            logging.info('skipping report on prominent item from {0} by {1}'.format(item_author, reporter_name))
            continue

        if item.author is not None and is_mod_rule_or_vile_report(report_reason, reporter_name):
            item.mod.remove()
            logging.info("removed item from {0} with {1} report from {2}".format(
                item_author, report_reason, reporter_name))

            if is_submission_report and not is_vile_report(report_reason, reporter_name):
                submission = r.submission(id=item.id)
                subreddit.flair.set(submission, text=rule_linkflair_mapping[report_reason], css_class=REMOVAL_FLAIR_CSS_CLASS)

            post_id = item.id if is_submission_report else item.link_id[3:]
            comment_id = None if is_submission_report else item.id
            if item_author in users and note_for_link_id_exists(users[item_author], post_id):
                logging.info('a usernote for user {0} and post id {1} already exists.'.format(item_author, post_id))
            else:
                logging.info('writing usernote for user {0} and post id {1}'.format(item_author, post_id))
                add_usernote_for_rule_violation(item_author, report_reason, reporter_name,
                                                post_id, comment_id, users, constants)

            return reporter_name

    return None


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
        subreddit = r.subreddit(subreddit_name)
        all_moderators = subreddit.moderator()
        submission_moderator_entries = filter(lambda mod: is_submission_moderator(mod), all_moderators)
        comment_moderator_entries = filter(lambda mod: is_comment_moderator(mod), all_moderators)
        submission_moderators = map(lambda m: m.name, submission_moderator_entries)
        comment_moderators = map(lambda m: m.name, comment_moderator_entries)

        modqueue = subreddit.mod.modqueue(limit=None)

        items_reported_as_rule_violation_by_mods = filter(has_mod_rule_reports, modqueue)

        usernotes_wrapper = usernotes.load_from_wiki_page(r, subreddit_name)
        json_data = usernotes_wrapper.compressed_json_data
        users = usernotes_wrapper.decoded_users_blob_json
        constants = json_data['constants']

        actions = defaultdict(list)
        for item in items_reported_as_rule_violation_by_mods:
            try:
                logging.info("processing mod reports on item {0}".format(item.id))
                reporter_name = process_rule_violation_report(item, subreddit, users, constants,
                                                              submission_moderators, comment_moderators)
                if reporter_name is not None:
                    actions[reporter_name].append(item.author.name)

            except Exception as e:
                logging.exception(e)

        if len(actions) > 0:
            edit_reason = 'added reports for {0}'.format(json.dumps(actions))
            truncated_edit_reason = edit_reason if len(edit_reason) < 250 else edit_reason[:250] + ' ... '
            usernotes.save_to_wiki_page(r, usernotes_wrapper, truncated_edit_reason, subreddit_name)
        else:
            logging.info("no processable mod reports found")

    except Exception as exception:
        logging.exception(str(exception))


if __name__ == '__main__':
    main()
