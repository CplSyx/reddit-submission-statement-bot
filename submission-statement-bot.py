#!/usr/bin/python3

# Notes
# Why are we excluding text posts, need to include that again for future use.
# Time limit seems to be set in multiple locations - need to walk through the logic to determine where it's getting taken from
# Some of this code feels redundant, can we simplify?

#Basic approach
#1) User posts
#2) Submission Bot (SB) posts a sticky telling the user they have x minutes to provide a submission statement of at least x length 
#3) If the user doesn't comply, SB deletes the post and notifies the user via a removal reason and a new sticky comment
#4) If the user does comply, SB deletes the sticky and posts a new sticky comment saying like "user has provided following reason: [...], please report post if this doesn't fit the sub"

# Edge cases 
# 1) Ignore moderator actions?
#       If a moderator has approved a post, we still require a SS
#       If a moderator has removed a post - ignore it.

# Rewrite
    # janitor fetch_submissions 
        # gets top submissions from the last day into self.submissions, excluding anything that has already been removed, or anything that has been moderator approved as this should override the bot
    # janitor handle_posts 
        # refreshes the existing list which updates the status of approval/removal
        # removes any newly approved/removed posts from the list
        # prunes submissions to get to a proper working list (prune_submissions needs to be reworked)
        # checks post via "serviced_by_janitor", which we use to determine if any action is needed
        # validate_submission_statement - 177 - needs a total rework
        # if "serviced" then we check for a valid SS already set (note, this is currently an in-memory value. Need to ensure the later steps don't cause duplication of pinned comment etc)
        # if no SS already then check for one 
        ##############CURRENTLY WORKING SECTION 447


#The current logic as per the code below 2023-11-02
    # janitor fetch_submissions gets submissions in last 30 minutes into self.submissions
    # janitor fetch_unmoderated gets whatever is in the modqueue
    # janitor removes fetch_unmoderated from fetch_submissions so that we have a shorter and "active" list
    # janitor handle_posts refreshes posts to check if moderated
        # add posts to anything unmoderated for a full list
        # for each post
            # check if serviced by the janitor -> skip if so
            # if time expired, check for submission statement (ss). Ignore text posts (why?)
                # if one comment from OP, validate ss text, otherwise take longest comment from OP
                # if ss valid, pin comment, if too short remove/report
                # if not report/remove
                # report if over a day old, report if mod approved without ss, remove if no ss
                # mark as serviced
                
        # sleep 5 minutes
    # janitor prune_unmoderated removes posts that are mod approved/removed from the list of unmoderated posts
    # every hour janitor prune_submissions removes stale posts older than 24 hours, reports older than 12 hours, and runs prune_unmoderated
    
    
            

# Goals:
# - check if post has submission statement
#   - configure whether you remove or report if there is no ss
#   - configure whether you remove or report if ss is not of sufficient length
# - corner cases:
#   - moderator already commented
#   - moderator already approved
#   - 
# Goals:
# - only allow certain flairs on certain days of the week
# - (e.g. casual friday)
#
#
# Constraints:
# - only check last 24 hours
#   - avoid going back in time too far
#   - remember which posts were approved
#   - probably want to pickle these, keep a sliding window
# - avoid rechecking the same posts repeatedly
# - recover if Reddit is down
# - want bot to be easily configurable
# - want a debug mode, so that collapsebot doesn't confuse people

import calendar
from configparser import ConfigParser
from datetime import datetime, timedelta
import praw
import time




###############################################################################
###
### Helper class -- settings base class
###
###############################################################################

class SubredditSettings:
    def __init__(self):
        # list of flair text, in lower case
        self.low_effort_flair = []
        self.removal_reason = cfg['TEXT']['removal_reason']
        self.submission_statement_time_limit_minutes = timedelta(hours=0, minutes=30)
        self.submission_statement_minimum_char_length = cfg['DEFAULT']['submission_statement_minimum_char_length']
        self.report_insufficient_length = False
        self.report_old_posts = False
        self.pin_submission_statement = cfg['DEFAULT']['pin_submission_statement']

    def post_has_low_effort_flair(self, post):
        flair = post._submission.link_flair_text
        if not flair:
            return False
        if flair.lower() in self.low_effort_flair:
            return True
        return False

    def submitted_during_casual_hours(self, post):
        return False

    def removal_text(self):
        return self.removal_reason

    def submission_statement_pin_text(self, submission_statement):
        # construct a message to pin, by quoting OP's submission statement
        # submission_statement is a top level comment
        return ""


###############################################################################
###
### Load Settings
###
###############################################################################

class SSBSettings(SubredditSettings):
    def __init__(self):
        super().__init__()
        self.removal_reason = cfg['TEXT']['removal_reason']
        self.submission_statement_minimum_char_length = cfg['DEFAULT']['submission_statement_minimum_char_length']
        self.report_insufficient_length = True
        self.pin_submission_statement = cfg['DEFAULT']['pin_submission_statement']

    def submission_statement_pin_text(self, ss):
        # construct a message to pin, by quoting OP's submission statement
        # ss is a top level comment, the submission statement

        verbiage = f"The following submission statement was provided by /u/{ss.author}:\n\n---\n\n"
        verbiage = verbiage + ss.body
        verbiage = verbiage + f"\n\n---\n\n Please reply to OP's comment here: https://www.reddit.com{ss.permalink}"
        return verbiage


###############################################################################
###
### Helper class -- wrapper for PRAW submissions
###
###############################################################################

class Post:
    def __init__(self, submission, time_limit=30):
        self._submission = submission
        self._created_time = datetime.utcfromtimestamp(submission.created_utc)
        self._submission_statement_validated = False
        self._submission_statement = None
        self._is_text_post = False
        self._post_was_serviced = False
        if submission.is_self:
            self._is_text_post = True
            self._post_was_serviced = True
        self._time_limit = time_limit

        # debugging
        #print(submission.title)
        #print("TIME EXPIRED?")
        #print(self.has_time_expired())

    def __eq__(self, other):
        return self._submission.permalink == other._submission.permalink

    def __hash__(self):
        return hash(self._submission.permalink)

    def __str__(self):
        return f"{self._submission.permalink} | {self._submission.title}"

    def validate_submission_statement(self):#, min_length):
        # identify and validate submission statement

        # return early if these checks already ran, and ss is proper
        if self._submission_statement_validated:
            #print("\tsubmission statement validated")
            return True

        # 1.) exempt text posts from this rule
        if self._submission.is_self:
            self._is_text_post = True 
            self._submission_statement_validated = True
            self._submission_statement = None
            # technically False, but True indicates everything is good, do not remove post
            #print("\tsubmission statement is self post; validated")
            return True

        # 2.) identify candidate submission statements. 
        # OP could have 1 or more top level replies
        ss_candidates = []
        for reply in self._submission.comments:
            if reply.is_submitter:
                ss_candidates.append(reply)

        # no SS
        if len(ss_candidates) == 0:
            self._is_text_post = False
            self._submission_statement_validated = False
            self._submission_statement = None
            #print("\tno submission statement identified; not validated")
            return False

        # one or more possible SS's
        if len(ss_candidates) == 1:
            self._submission_statement = ss_candidates[0]
            self._is_text_post = False
            self._submission_statement_validated = True
            #print("\tsubmission statement identified from single comment; validated")
            return True
        else:
            for candidate in ss_candidates:
                text = candidate.body
                text = text.lower().strip().split()
                if "submission" in text and "statement" in text:
                    self._submission_statement = candidate
                    break
                elif "ss" in text:
                    self._submission_statement = candidate
                    break

                # otherwise, take the longest top level comment from OP
                if self._submission_statement:
                    if len(candidate.body) > len(self._submission_statement.body):
                        self._submission_statement = candidate
                else:
                    self._submission_statement = candidate
            #print("\tsubmission statement identified from multiple comments; validated")
            self._is_text_post = False
            self._submission_statement_validated = True 
            return True

        # this check is actually done later
        # just check to see if a submission statement exists
        ## 3.) check if submission statement is of proper length
        #if self._submission_statement and (len(self._submission_statement.body) >= min_length):
        #    self._submission_statement_validated = True 
        #    return True

        # unable to validate submission statement
        #print("\tunknown case occurred; no submission statement found; not validated")
        self._submission_statement_validated = False
        return False

    def has_time_expired(self):
        # True or False -- has the time expired to add a submission statement?
        return (self._created_time + self._time_limit < datetime.utcnow())

    def is_moderator_approved(self):
        print(f"Moderator approved? {self._submission.approved}\n\t")
        return self._submission.approved

    def is_post_removed(self):
        return self._submission.removed

    def refresh(self, reddit):
        self._submission = praw.models.Submission(reddit, id = self._submission.id)

    def serviced_by_janitor(self, janitor_name):
        # ~return true if there is a top level comment left by the Janitor~
        # don't care if stickied, another mod may have unstickied a comment
        
        # if we are using janitor comments to ask for responses, we can't just rely on a top-level janitor comment to say it's been serviced. We need to look for specific details *in* that comment.
        # But we CAN still use this thread to determine if no action has been taken.

        
        if self._post_was_serviced:
            return True

        self._post_was_serviced = False
        for reply in self._submission.comments:
            if reply and reply.author and reply.author.name:
                #print(f"\t\treply from: {reply.author.name}")
                if reply.author.name == janitor_name:
                    self._post_was_serviced = True 
                    break
        return self._post_was_serviced


    def report_post(self, reason):
        self._submission.report(reason)
        self._post_was_serviced = True

    def report_submission_statement(self, reason):
        self._submission_statement.report(reason)
        self._post_was_serviced = True

    def reply_to_post(self, reason, pin=True, lock=False):
        removal_comment = self._submission.reply(reason)
        removal_comment.mod.distinguish(sticky=pin)
        if lock:
            removal_comment.mod.lock()
        self._post_was_serviced = True


    def remove_post(self, reason, note):
        self._submission.mod.remove(spam=False, mod_note=note)
        removal_comment = self._submission.reply(reason)
        removal_comment.mod.distinguish(sticky=True)



###############################################################################
###
### Main worker class -- the bot logic
###
###############################################################################

class Janitor:
    def __init__(self, subreddit):
        self.reddit = praw.Reddit(
                        client_id = cfg['CREDENTIALS']['client_id'],
                        client_secret = cfg['CREDENTIALS']['client_secret'],
                        user_agent = "linux:mmm_submission_bot:v0.1",                        
                        username = cfg['CREDENTIALS']['username'],
                        password = cfg['CREDENTIALS']['password']
        )
        self.username = cfg['CREDENTIALS']['username']
        self.subreddit = self.reddit.subreddit(subreddit)
        self.mod = self.subreddit.mod
        self.submissions = set()
        self.unmoderated = set()
        self.sub_settings = SubredditSettings()

        self._last_submission_check_time = None
        self._last_unmoderated_check_time = None


    def set_subreddit_settings(self, sub_settings):
        self.sub_settings = sub_settings


    def refresh_posts(self):
        # want to check if post.removed or post.approved, in order to do this,
        # must refresh running list. No need to check the queue or query again
        #
        # this method is necessary because Posts dont have a Reddit property
        for post in self.submissions:
            post.refresh(self.reddit)

        for post in self.unmoderated:
            post.refresh(self.reddit)


    def fetch_submissions(self):
        submissions = set()
        newposts = self.subreddit.top(time_filter="day")
            # we could use self.subreddit.new() but this would return 1000 posts and we won't get 1000 posts a day so this will give us a shorter list
        for post in newposts:

            # we don't care about posts that have already been removed or if they have been moderator approved as that overrules the SS bot
            if not (post.is_moderator_approved() or post.is_post_removed()):
                submissions.add(Post(post))

        #self.submissions = submissions
        return submissions
    
    def update_submission_list(self):
        self.submissions = self.fetch_submissions()

# We don't want to ignore all unmoderated posts, because we still want to put a SS reminder on them even if they're in the queue. 
# Think in that case we don't need the following code.
    def fetch_unmoderated(self):
        # loop through filtered posts, want to remove shit without submission statements
        unmoderated = set()
        for post in self.mod.unmoderated():
            # this might be the better one to loop through...
            # why loop through stuff that's already been approved?
            # useful only for double-checking mod actions...
            print("__UNMODERATED__")
            print(post.title)
            unmoderated.add(Post(post, self.sub_settings.submission_statement_time_limit_minutes))
            self.unmoderated.add(Post(post, self.sub_settings.submission_statement_time_limit_minutes))

        # want to remove items from submissions that are in unmoderated
        # and leave unmoderated alone
        self.submissions = self.submissions - unmoderated
        return unmoderated 

# Next block won't be needed as we're already ignoring mod approved or removed posts
    def prune_unmoderated(self):
        # want to remove submissions from running list that have been checked 
        # for submission statement, that are no longer unmoderated
        self.refresh_posts()

        unmoderated = self.fetch_unmoderated()
        moderated = self.unmoderated - unmoderated
        for post in moderated:
            if post.is_moderator_approved() or post.is_post_removed():
                self.unmoderated.remove(post)

# This is about flagging "old" posts without actions. Do we care?
# Need to include a removal of the removed/approved posts here after the refresh
    def prune_submissions(self):
        self.refresh_posts()

        last24h = self.fetch_submissions()
        stale = self.submissions - last24h
        for post in stale:
            if post.is_moderator_approved() or post.is_post_removed():
                self.unmoderated.remove(post)
            else:
                if self.sub_settings.report_old_posts:
                    reason = "This post is over 24 hours old and has not been moderated. Please take a look!"
                    self.report_post(reason)
                self.unmoderated.remove(post)

        # report anything over 12 hours old that hasn't been serviced
        if self.sub_settings.report_old_posts:
            now = datetime.utcnow()
            for post in self.submissions:
                if post._created_time + timedelta(hours=12, minutes=0) < now:
                    reason = "This post is over 12 hours old and has not been moderated. Please take a look!"
                    post.report_post(reason)



    def handle_posts(self):
        self.refresh_posts()
        self.prune_submissions()

        all_posts = self.submissions #.union(self.unmoderated)
        
        for post in all_posts:
            print(f"Checking post: {post._submission.title}\n\t{post._submission.permalink}...")

            if post.serviced_by_janitor(self.username):
                print("\tPost has been serviced")
                # We've interacted with this post before

            if post._submission_statement_validated:
                print("\tSubmission statement validated")
                # We've checked the SS and it's good - skip
                continue              

            # So at this point the post either hasn't been seen at all, or it hasn't had the SS validated.
            # First let's check for a valid SS
            if post.has_time_expired():
                print("\tTime has expired")
                # check if there is a submission statement
                # yes -> 
                if post.validate_submission_statement():
                    if not post._submission_statement:
                        print("No submission statement")
                        ###### Action here to remove post
                        continue
                    print("\tPost has submission statement")

                    # We need to delete our original comment and pin the submission statement. This logic here is currently incorrect.
                    if self.sub_settings.pin_submission_statement:
                        post.reply_to_post(self.sub_settings.submission_statement_pin_text(post._submission_statement), pin=self.sub_settings.pin_submission_statement, lock=True)
                        print(f"\tPinning submission statement: \n\t{post._submission.title}\n\t{post._submission.permalink}")

                    # does the submission statement have the required length?
                    #   yes -> (NOP)
                    #   no -> report or remove, depending on subreddit settings
                    if not len(post._submission_statement.body) >= self.sub_settings.submission_statement_minimum_char_length:
                        reason = "Submission statement is too short"
                        if self.sub_settings.report_insufficient_length:
                            post.report_post(reason)
                            print(f"\tReporting post: \n\t{post._submission.title}\n\t{post._submission.permalink}")
                            print(f"\tReason: {reason}\n---\n")
                        else:
                            post.remove_post(self.sub_settings.removal_reason, reason)
                            print(f"\tRemoving post: \n\t{post._submission.title}\n\t{post._submission.permalink}")
                            print(f"\tReason: {reason}\n---\n")
                    else:
                        #print(f"\tSS has proper length: \n\t{post._submission.title}\n\t{post._submission.permalink}")
                        print(f"\tSS has proper length \n\t{post._submission.permalink}")
                else:
                    print("\tpost does NOT have submission statement")
                    now = datetime.utcnow()
                    # did a mod approve, or is it more than 1 day old?
                    #   yes -> report 
                    #   no -> remove and pin removal reason
                    if post._created_time + timedelta(hours=24, minutes=0) < now:
                        reason = "Post is more than 1 day old and has no submission statement. Please take a look."
                        post.report_post(reason)
                        print(f"\tReporting post: \n\t{post._submission.title}\n\t{post._submission.permalink}")
                        print(f"\tReason: {reason}\n---\n")
                    elif post.is_moderator_approved():
                        reason = "Moderator approved post, but there is no SS. Please double check."
                        post.report_post(reason)
                        print(f"\tReporting post: \n\t{post._submission.title}\n\t{post._submission.permalink}")
                        print(f"\tReason: {reason}\n---\n")
                    else:
                        reason = "no submission statement"
                        post.remove_post(self.sub_settings.removal_reason, reason)
                        print(f"\tRemoving post: \n\t{post._submission.title}\n\t{post._submission.permalink}")
                        print(f"\tReason: {reason}\n---\n")
                post._post_was_serviced = True

            else:
                print("\tTime has not expired")

                # indicate post serviced by Janitor

def go():
    # Settings load
    fs = SSBSettings()
    jannie = Janitor(cfg['DEFAULT']['subreddit'])
    jannie.set_subreddit_settings(fs)
    while True:
        try:
            jannie.update_submission_list()

            # Wait 5 minutes (300 seconds)
            time.sleep(300)

        except Exception as e:
            print(repr(e))
            print("\n")
            print("Restarting...\n")

def run_forever():
    five_min = 60 * 5
    one_hr  = five_min * 12
    print("Running run_forever\n")
    while True:
        try:
            fs = SSBSettings()
            jannie = Janitor(cfg['DEFAULT']['subreddit'])
            jannie.set_subreddit_settings(fs)
            jannie.update_submission_list()
            jannie.fetch_unmoderated()
            counter = 1
            while True:
                print("Handling posts")
                # handle posts
                jannie.handle_posts()
                # every 5 min prune unmoderated
                time.sleep(five_min)
                jannie.prune_unmoderated()

                # every 1 hour prune submissions
                if counter == 0:
                    jannie.prune_submissions()
                counter = counter + 1
                counter = counter % 12

            # every hour, check all posts from the day
            # every 5 minutes, check unmoderated queue
        except Exception as e:
            print(repr(e))
            #print("Reddit outage? Restarting....")

        time.sleep(60) #THIS WAS CHANGED FROM five_min

def run():
    five_min = 60 * 5
    one_hr  = five_min * 12
    while True:
        fs = SSBSettings()
        jannie = Janitor(cfg['DEFAULT']['subreddit'])
        jannie.set_subreddit_settings(fs)
        jannie.update_submission_list()
        jannie.fetch_unmoderated()
        counter = 1
        while True:
            # handle posts
            jannie.handle_posts()
            # every 5 min prune unmoderated
            time.sleep(five_min)
            jannie.prune_unmoderated()

            # every 1 hour prune submissions
            if counter == 0:
                jannie.prune_submissions()
            counter = counter + 1
            counter = counter % 12

        # every hour, check all posts from the day
        # every 5 minutes, check unmoderated queue

        time.sleep(five_min)


def run_once():
    fs = SSBSettings()
    jannie = Janitor(cfg['DEFAULT']['subreddit'])
    jannie.set_subreddit_settings(fs)
    #posts = jannie.fetch_submissions()
    #unmoderated = jannie.fetch_unmoderated()
    jannie.update_submission_list()
    jannie.handle_posts()
    #for post in posts:
    #    print(post.title)
    #    print("___")


if __name__ == "__main__":
    cfg = ConfigParser()
    cfg.read("maybemaybemaybe.cfg")
    #run_once()
    run_forever()