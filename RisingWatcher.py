import logging
import logging.config
import re
from datetime import datetime

import praw

POST_SCORE_THRESHOLD_FOR_ALL_RISING = 75
POST_SCORE_THRESHOLD_FOR_FIRST_30_MIN = 35

submission_link_regex = re.compile('/comments/([^/]+)/', re.IGNORECASE)

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
        alert_subject = 'Quickly rising post alert'
        recently_processed_links = set()
        bot_account = r.user.me()
        for sent_message in r.inbox.sent(limit=50):
            if sent_message.author == bot_account and sent_message.parent_id is None \
                    and alert_subject in sent_message.subject:
                for submission_link in re.findall(submission_link_regex, sent_message.body):
                    recently_processed_links.add(submission_link)
        logging.debug('Recently processed rising alerts to be ignored: {0}'.format(recently_processed_links))

        subreddit = r.subreddit(subreddit_name)

        for rising_post in subreddit.rising():
            post_score = rising_post.score
            post_age = datetime.utcnow() - datetime.utcfromtimestamp(rising_post.created_utc)
            post_age_in_minutes = post_age.seconds / 60
            post_author = '/u/{0}'.format(rising_post.author.name) if rising_post.author is not None else '[deleted]'
            not_recently_processed = rising_post.id not in recently_processed_links
            if (not_recently_processed
                and (post_score >= POST_SCORE_THRESHOLD_FOR_ALL_RISING
                     or (post_score >= POST_SCORE_THRESHOLD_FOR_FIRST_30_MIN and post_age_in_minutes < 30))):
                print 'Writing alert mail for post {0}'.format(rising_post)
                msg = 'The following submission by {0} has reached a score of {1} in just {2} minutes: ' \
                      '\n\n{3}'.format(post_author, post_score, post_age_in_minutes, rising_post.permalink)

                subreddit.message(alert_subject, msg)

        logging.info('done checking rising submissions')

    except Exception as exception:
        logging.exception(exception)


if __name__ == '__main__':
    main()
