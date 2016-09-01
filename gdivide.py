import os
import httplib2
import oauth2client
import argparse
import sys
import shutil
import email
import base64
import simhash
import io
import time
import googleapiclient
import progressbar
import urllib
import re

from six.moves.html_parser import HTMLParser
from email.header import decode_header
from datetime import timedelta, datetime
from dateutil.parser import parse

from apiclient import discovery
from oauth2client import client
from oauth2client import tools

parser = argparse.ArgumentParser(parents=[tools.argparser])
parser.add_argument(
    '--private-correspondents',
    help="Email address(es) that you want to cleanse from your work address and move to home address",
    nargs='+',
)
parser.add_argument(
    '--work-gmail',
    help="Work gmail address (to move messages *from*)",
)
parser.add_argument(
    '--home-gmail',
    help="Home gmail address (to move messages *to*)",
)
parser.add_argument(
    '--dry-run',
    action="store_true",
    help="Don't make any modifications",
)
parser.add_argument(
    '--clear-credentials',
    action='store_true',
    help='Delete saved OAuth credentials (will wipe entire ~/.gdivide-credentials directory)',
)
parser.add_argument(
    '--skip-deduplicate',
    action='store_true',
    help='Skip duplicate detection - may create duplicates',
)
parser.add_argument(
    '--limit',
    type=int,
    default=None,
    help='Limit to processing this number of messages',
)

flags = parser.parse_args()


SCOPES = 'https://www.googleapis.com/auth/gmail.modify'
CLIENT_SECRET_FILE = 'client_secret.json'
APPLICATION_NAME = 'GDivide'
DIRECTIONS = ['to', 'from']
LABEL_NAME = 'gdivide'
SIMHASH_DISTANCE = 3


def _credential_dir():
    home_dir = os.path.expanduser('~')
    credential_dir = os.path.join(home_dir, '.gdivide-credentials')
    return credential_dir


def get_credentials(email, email_type="Unknown"):
    """
    Get and locally cache OAuth credentials.
    """
    if not os.path.exists(_credential_dir()):
        os.makedirs(_credential_dir())
    credential_path = os.path.join(_credential_dir(), "{}.json".format(email))
    store = oauth2client.file.Storage(credential_path)
    credentials = store.get()
    if not credentials or credentials.invalid:
        print(u"************************************************************************")
        print(u"Please authorize for your {} ({}) gmail account.".format(email, email_type))
        print(u"************************************************************************")
        flow = client.flow_from_clientsecrets(
            filename=CLIENT_SECRET_FILE,
            scope=SCOPES,
            login_hint=email,
        )
        flow.user_agent = APPLICATION_NAME
        credentials = tools.run_flow(flow, store, flags)
        http = credentials.authorize(httplib2.Http())
        service = discovery.build('gmail', 'v1', http=http)
        resp = self._execute(service.users().getProfile(userId='me'), retries=0)
        if not resp['emailAddress'] == email:
            clear_credentials()
            print(u"ERROR: email address does not match credentials.")
            print(u"Stored credentials cleared - you will need to re-authenticate.")
            sys.exit(1)
    return credentials


def clear_credentials():
    if os.path.exists(_credential_dir()):
        shutil.rmtree(_credential_dir(), ignore_errors=True)
    else:
        print(u"No saved credentials found")
    return sys.exit(0)


class Divider:

    def __init__(self, home_credentials, work_credentials,
            private_correspondents, limit=None, skip_deduplicate=False,
            dry_run=False):
        self.private_correspondents = private_correspondents
        home_http = home_credentials.authorize(httplib2.Http())
        work_http = work_credentials.authorize(httplib2.Http())
        self.home_service = discovery.build('gmail', 'v1', http=home_http)
        self.work_service = discovery.build('gmail', 'v1', http=work_http)
        self.limit = limit
        self.skip_deduplicate = skip_deduplicate
        self._label = None
        self.dry_run = dry_run
        self.thread_map = {}
        self.stats_inserted = 0
        self.stats_trashed = 0

    def run(self):
        """Entry point
        """
        resp = self.get_private_messages_from_work()
        messages = resp['messages']
        if self.limit is not None:
            messages = messages[:self.limit]
        self.bar = progressbar.ProgressBar(redirect_stdout=True, max_value=len(messages))
        for i, message_id in enumerate(messages):
            if self.dry_run:
                print(u"Moving message with id {} (dry run - no changes will be made!)".format(message_id))
            else:
                print(u"Moving message with id {}".format(message_id))
            # Obeys `dry_run`
            self.move_message(message_id)
            self.bar.update(i + 1)
        print('Finished - created {} messages, trashed {}'.format(self.stats_inserted, self.stats_trashed))

    def get_or_create_label(self):
        """Ensures that uploaded messages have the gdivide label set
        """
        if self._label:
            return self._label
        resp = self._execute(self.home_service.users().labels().list(userId='me'))
        for label in resp['labels']:
            if label['name'] == LABEL_NAME:
                self._label = label
                return self._label
        if self.dry_run:
            print(u"Would have created label {}".format(LABEL_NAME).encode('utf-8'))
        else:
            label = self._execute(self.home_service.users().labels().create(userId='me',
                body={
                    'messageListVisibility': 'hide',
                    'name': LABEL_NAME,
                    'labelListVisibility': 'labelHide',
                }))
            print(u"Created label with id {}".format(label['id']))
            self._label = label
        return self._label

    def _get_messages_page(self, service, query, fields=None, page_token=None, obey_limit=False):
        print(u"Getting results page for query {}".format(query).encode('utf-8'))
        resp = self._execute(service.users().messages().list(
            userId='me',
            q=query,
            pageToken=page_token,
            fields=fields,
        ))
        return resp

    def _get_messages(self, service, query, fields=None, obey_limit=True):
        all_messages = []
        resp = self._get_messages_page(service, query=query, fields=fields)
        if 'messages' in resp:
            all_messages.extend(resp['messages'])
        while 'nextPageToken' in resp:
            resp = self._get_messages_page(self.work_service, query=query,
                fields=fields, page_token=resp['nextPageToken'])
            try:
                all_messages.extend(resp['messages'])
            except:
                pass
            if self.limit:
                if obey_limit is True and len(all_messages) >= self.limit:
                    break
        return all_messages

    def get_private_messages_from_work(self):
        """Gets a list of message ids matching private_correspondents

        Returns: dict with two keys, `threads` and `messages`
        """
        all_messages = []
        for correspondent in self.private_correspondents:
            for direction in DIRECTIONS:
                query = u'{}:{}'.format(direction, correspondent)
                all_messages.extend(self._get_messages(self.work_service, query, obey_limit=True))
        all_threads = [i['threadId'] for i in all_messages]
        all_threads = list(set(all_threads))
        all_messages = [i['id'] for i in all_messages]
        all_messages = list(set(all_messages))
        print(u"Found {} messages ({} threads) sent {} {}".format(
            len(all_messages),
            len(all_threads),
            '/'.join(DIRECTIONS),
            ', '.join(self.private_correspondents),
        ))
        return {
          'threads': all_threads,
          'messages': all_messages,
        }

    def move_message(self, message_id):
        """Moves a message FROM work TO home email.

        Unless --skip-deduplicate is set, this will check for duplicates by:
        """
        message = self.get_raw_message(self.work_service, message_id)
        duplicate = None
        # If not a duplicate or checking turned off, put message and
        # delete original
        if not self.skip_deduplicate:
            duplicate = self.check_duplicate(message)
        if self.skip_deduplicate or not duplicate:

            if message['threadId'] in self.thread_map:
                thread_id = self.thread_map[message['threadId']]
            else:
                thread_id = None

            if self.dry_run:
                print(u"Would have inserted message id {}: (size {}) {}".format(message_id,
                    len(message['raw']), self._get_snippet(message)).encode('utf-8'))
            else:
                print(u"Inserting message id {}: {}".format(message_id,
                    self._get_snippet(message)).encode('utf-8'))
                attachments = []
                raw = message['raw']
                body = {
                    'labelIds': [self.get_or_create_label()['id']],
                }
                if thread_id:
                    body['threadId'] = thread_id
                b = io.BytesIO()
                message_bytes = base64.urlsafe_b64decode(message['raw'].encode('ASCII'))
                b.write(message_bytes)
                media_body = googleapiclient.http.MediaIoBaseUpload(b, mimetype='message/rfc822')
                resp = self._execute(self.home_service.users().messages().insert(
                    userId='me',
                    internalDateSource='dateHeader',
                    body=body,
                    media_body=media_body,
                ))
                self.stats_inserted += 1
                # Add mapping between old and new threads
                self.thread_map[message['threadId']] = resp['threadId']
            if self.dry_run:
                print(u"Would have trashed original message {}".format(message_id))
            else:
                print(u"Trashing original message {}".format(message_id))
                resp = self.trash_message(message_id)
                self.stats_trashed += 1
        else:
            print(u"Skipping message id {}: found duplicate {} in target".format(
                message_id, duplicate))
            if self.dry_run:
                print(u"Would have trashed original message {}".format(message_id))
            else:
                print(u"Trashing original message {}".format(message_id))
                resp = self.trash_message(message_id)
                self.stats_trashed += 1
        self.bar.update()

    def trash_message(self, message_id):
        """Moves original message to trash"""
        return self._execute(
            self.work_service.users().messages().trash(
                userId='me',
                id=message_id
            )
        )

    def get_raw_message(self, service, message_id):
        """
        Gets the message from selected account.

        Encoded raw form is available as `raw` key of returned dict
        """
        try:
            message = self._execute(service.users().messages().get(userId='me',
                id=message_id, format='raw'))
        except googleapiclient.errors.HttpError:
            return None
        msg_str = base64.urlsafe_b64decode(message['raw'].encode('ASCII'))
        mime_msg = email.message_from_string(msg_str)
        message['decoded'] = mime_msg
        return message

    def check_duplicate(self, message):
        """Checks to see if `message` already exists in home gmail.

        There's no easy way of doing this because GMail doesn't allow you
        to search for a message hash.

        Instead, we:

        *   Search for the same subject with the same datestamp
        *   Download any messages that match
        *   Compare the raw message bodies against each other
        *   Return True if they match

        Returns: id of duplicate message if message already exists, None otherwise
        """
        subject = self._get_subject(message)
        date = self._get_date(message)
        snippet = self._get_snippet(message)
        from_date = date # sic
        to_date = date + timedelta(days=1)
        clean_pattern = r'[^\w\s0-9\']'
        query = u"subject:\"{}\" after:{} before:{} \"{}\"".format(
            re.sub(clean_pattern, ' ', subject),
            from_date.strftime('%Y/%m/%d'),
            to_date.strftime('%Y/%m/%d'),
            re.sub(clean_pattern, ' ', snippet),
        )
        similar_messages = self._get_messages(
            self.home_service,
            query=query,
        )
        if similar_messages:
            for pd in similar_messages:
                potential_duplicate = self.get_raw_message(self.home_service, pd['id'])
                if self._check_message_duplicate(message, potential_duplicate):
                    return potential_duplicate['id']
        return None

    def _check_message_duplicate(self, message1, message2):
        """Checks messages.

        Currently just compares first part of payload content but in future will want to
        compare all payloads as the first bit may vary for legitimate reasons.

        Returns `True` if `message1` and `message2` are duplicates, `False` otherwise
        """
        if (not message1) or (not message2):
            return False
        if message1['raw'] == message2['raw']:
            return True
        email1 = email.message_from_string(base64.urlsafe_b64decode(message1['raw'].encode('ASCII')))
        email2 = email.message_from_string(base64.urlsafe_b64decode(message2['raw'].encode('ASCII')))
        if (not email1.is_multipart()) and (not email2.is_multipart()):
            if email1.get_payload() == email2.get_payload():
                return True
            else:
                return False
        elif email1.is_multipart() and email2.is_multipart():
            if len(email1.get_payload()) != len(email2.get_payload()):
                return False
            charset1 = email1.get_payload(0).get_content_charset() or 'utf-8'
            charset2 = email2.get_payload(0).get_content_charset() or 'utf-8'
            try:
                payload1 = str(email1.get_payload(0)).decode(charset1)
                payload2 = str(email2.get_payload(0)).decode(charset2)
            except: # Wrong encoding? Or just mangled? Who knows.
                return False
            distance = simhash.Simhash(payload1).distance(simhash.Simhash(payload2))
            print(u"Similarity distance between messages is {}".format(distance))
            self.bar.update()
            if distance < SIMHASH_DISTANCE: # MAGIC NUMBER - no idea what this should be
                return True
            else:
                return False
        else:
            return False

    def _get_subject(self, message):
        for h, v in message['decoded'].items():
            if h.lower() == u'subject':
                try:
                    res = email.header.decode_header(v)
                    return res[0][0].decode(res[0][1])
                except:
                    return v
        return u""

    def _get_date(self, message):
        """This is a timestamp
        """
        return datetime.fromtimestamp(float(message['internalDate'])/1000)

    def _get_snippet(self, message):
        """
        """
        h = HTMLParser()
        unescaped = h.unescape(message['snippet'])
        return unescaped

    def _execute(self, fn, retries=2, fail_hard=True):
        try:
            return fn.execute()
        except googleapiclient.errors.HttpError as e:
            if retries == 0:
                if fail_hard is True:
                    raise e
                else:
                    import ipdb; ipdb.set_trace()
                    print(u'Error', e.message)
                    return {'error': True}
            elif retries > 0:
                print(u'Retrying failed GMail API request')
                retries -= 1
                time.sleep(5)
                return self._execute(fn, retries=retries, fail_hard=fail_hard)



def main():
    if flags.clear_credentials:
        clear_credentials()
        print(u'Credentials cleared!')
    else:
        client = Divider(
            home_credentials=get_credentials(email=flags.home_gmail,
                email_type='home'),
            work_credentials=get_credentials(email=flags.work_gmail,
                email_type='work'),
            private_correspondents=flags.private_correspondents,
            limit=flags.limit,
            skip_deduplicate=flags.skip_deduplicate,
            dry_run=flags.dry_run,
        )
        client.run()


if __name__ == '__main__':
    main()