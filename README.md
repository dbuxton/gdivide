# GDivide

A simple command-line tool to divide your personal GMail from your work Google Apps/GMail account. Remove personal messages from your work accounts while still keeping them available in the cloud.

Uses the [GMail API](https://developers.google.com/gmail/api/v1/reference).

## Why use

You have a work email on Google Apps and a personal GMail (or Google Apps) account. Your significant other (or mother, or dogsitter) sometimes sends you stuff to your work address, which you want to keep, but don't want to share with your assistant/auditor/etc.

This tool lets you move personal messages that have somehow leaked into your work account back to your personal account. It maintains threads and tries (pretty successfully) to deduplicate based on message content. 

Essentially all GDivide does is:

*   Search for emails **to** or **from** your `private-correspondents` in your **work** email
*   Check each message to see whether you already have it in your **private** email
    *   If not, copy them and delete original
    *   If so, just delete the original

### Why not use [Thunderbird, Outlook, another IMAP client] instead?

With a bit of patience you can get the same result from using an IMAP client to transfer messages. 
However things like correct date display on imported messages can be a crapshoot, and processing 
large numbers (or even small numbers) of messages in Thunderbird or Outlook is no fun.

This tool does not work perfectly but it's much better than dragging 5,000 messages between Outlook mailboxes.

## Limitations

*   Only works with GMail accounts
*   May result in duplicates (if e.g. some work-account messages were copied to, or forwarded from, your personal account). Tries to do deduplication using [simhash](https://github.com/leonsim/simhash) but YMMV. You can disable deduplication with the `--skip-deduplicate` option.
*   Very wasteful in terms of requests - does several requests for each message rather than [batch API](https://developers.google.com/gmail/api/guides/batch)
*   Only filtering by sender/addressee email address is supported. If you want to erase all mentions of a person from your email, you will have to send a PR ;)
*   Does not alter backups or [Google Vault](https://www.google.com/work/apps/business/products/vault/) audit history of your email
*   Doesn't transfer or delete chats - you will have to do that manually
*   You may hit GMail API rate limits (`429` errors)

## Lack of warranty

By default (see **Options** below) `gdivide` will make changes to BOTH email accounts that you give it. It may result in you losing data (although it doesn't delete anything irrevocably, just moves to trash, so you should be able to undo any changes if you need to as long as you move quick-ish). You should make sure you have backups of any important data before using it. If you want to get a full dump of your email data you can do so via [Google Takeout](https://www.google.com/settings/takeout).

I take no responsibility for any damage resulting from use of this tool, howsoever caused, including by negligence.

### Inclusion of client secret in this repo

Based on https://developers.google.com/identity/protocols/OAuth2InstalledApp - in particular

> Installed apps are distributed to individual machines, and it is assumed that these apps cannot keep secrets.

I am distributing this app with oauth secret available in the code. I may revoke this at any time for any or no reason if there is any abuse associated with it.

## Usage

1.  Clone repo
2.  `pip install -r requirements.txt`
3.  `python gdivide.py --work-gmail me@work.com --home-gmail me@personal.com --private-correspondents girlfriend@example.com mum@gmail.com`
4.  Sit back and wait. Possibly a really long time depending on number of messages and their size. (GDivide copies attachments too).
5.  Empty work email trash to permanently remove transferred email. BE CAREFUL!

### Options

    --work-gmail [name@example.com]
        The account you want to move emails FROM.
        WARNING: EMAILS IN THIS ACCOUNT MAY GET TRASHED/DELETED
    --home-gmail [name@example.com]
        The account you want to move emails TO.
        WARNING: EMAILS WILL BE ADDED TO THIS ACCOUNT
    --private-correspondents PRIVATE_CORRESPONDENTS [PRIVATE_CORRESPONDENTS ...]
        Email address(es) that you want to cleanse from your
        work google account and move to home gmail
    --limit [INT]
        Only process this many messages
    --dry-run
        Don't actually make any changes to either home or work accounts
    --skip-deduplicate
        Don't attempt to deduplicate based on existing emails in target inbox
    --clear-credentials
        Delete any stored OAuth credentials

## Why I wrote it

IMAP is a pain, and I wanted to see if the GMail API was any better.

The short story is, yes and no. In practice you seem to have to learn about MIME encodings, multipart email structures and a load of other things to do anything remotely useful, and the documentation leaves a lot to be desired.

However if you want to do simple things, it's a lot easier to understand than IMAP.

## Privacy

This app doesn't collect any data from users. You do need to sign in with Google to use it, and what they do with your data is between you and them.

## License

Copyright (c) 2021 David Buxton

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
