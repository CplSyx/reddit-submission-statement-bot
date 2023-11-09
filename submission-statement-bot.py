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
#      DONE (I think, this is normal behaviour so we just haven't included a specific scenario for "approved" posts) If a moderator has approved a post, we still require a SS
#      DONE If a moderator has removed a post - ignore it.
# 2) Moderator posts 
#      DONE If a moderator makes a post and it is distinguished as such (i.e. a top level sticky etc.) then we should ignore it.
# 3) Too many posts...
#       What if we get an influx of posts and we can't deal with them all? At the moment every single post is reprocessed fully. We need to prune the "submission" list to remove anything that the bot has already validated before it hits handle_posts - ideally in update_submission_list

# Rewrite
    # janitor fetch_submissions 
        # gets top submissions from the last day into self.submissions, excluding anything that has already been removed, or anything that has been moderator approved as this should override the bot
    # janitor handle_posts 
        # refreshes the existing list which updates the status of approval/removal
        # removes any newly approved/removed posts from the list
        # prunes submissions to get to a proper working list (prune_submissions needs to be reworked)
        # checks post via "serviced_by_janitor", which we use to determine if any action is needed
        # validate_submission_statement - 177 - needs a total rework (Done I think? now candidate_submission_statement)
        # if "serviced" then we check for a valid SS already set (note, this is currently an in-memory value. Need to ensure the later steps don't cause duplication of pinned comment etc)
        # if no SS already then check the time - do we need to act
        # if the time limit has passed, check for a valid SS
        # check the length, if too short remove/report
        # otherwise assume it's good and we will need to post the SS as a comment
#### VALIDATE COMPLETE FLOW NOW AND REWRITE ABOVE
# Todo: Tidy up settings classes - why do we have two
# Remove any unused code 


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
from configparser import ConfigParser, ExtendedInterpolation
from datetime import datetime, timedelta
import praw
import time
import sys




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
        self.submission_statement_request_text = str(cfg['TEXT']['submission_statement_request'])
        self.submission_statement_time_limit_minutes = int(cfg['DEFAULT']['minutes_to_wait_for_submission_statement'])
        self.submission_statement_minimum_char_length = int(cfg['DEFAULT']['submission_statement_minimum_char_length'])
        self.report_insufficient_length = True
        self.remove_posts = cfg['DEFAULT'].getboolean('remove_posts')
        self.pin_submission_statement_request = cfg['DEFAULT'].getboolean('pin_submission_statement_request')
        self.pin_submission_statement_response = cfg['DEFAULT'].getboolean('pin_submission_statement_response')
        self.remove_request_comment = cfg['DEFAULT'].getboolean('bot_cleanup')


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

    def submission_statement_quote_text(self, submission_statement):
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
        super().__init__() #Why? We can just use this class can't we?
        self.removal_reason = str(cfg['TEXT']['removal_reason'])
        self.submission_statement_time_limit_minutes = int(cfg['DEFAULT']['minutes_to_wait_for_submission_statement'])
        self.submission_statement_request_text = str(cfg['TEXT']['submission_statement_request'])
        self.submission_statement_minimum_char_length = int(cfg['DEFAULT']['submission_statement_minimum_char_length'])
        self.report_insufficient_length = True
        self.remove_posts = cfg['DEFAULT'].getboolean('remove_posts')
        self.pin_submission_statement_request = cfg['DEFAULT'].getboolean('pin_submission_statement_request')
        self.pin_submission_statement_response = cfg['DEFAULT'].getboolean('pin_submission_statement_response')
        self.submission_reply_spoiler = cfg['DEFAULT'].getboolean('use_spolier_tags')

    def submission_statement_quote_text(self, ss, spoilers):
        # Construct the quoted message, by quoting OP's submission statement

        verbiage = f"The following submission statement was provided by u/{ss.author}:\n\n---\n\n"
        if(spoilers):
            verbiage = verbiage + ">!" + ss.body + "!<"
        else:
            verbiage = verbiage + ss.body
        verbiage = verbiage + f"\n\n---\n\n Does this explain the post? Please report this post for moderator attention if not."
        return verbiage


###############################################################################
###
### Helper class -- wrapper for PRAW submissions
###
###############################################################################

class Post:
    def __init__(self, submission, time_limit_minutes=30):
        self._submission = submission
        self._created_time = datetime.utcfromtimestamp(submission.created_utc)
        self._submission_statement_validated = False
        self._submission_statement = None
        self._post_was_serviced = False
        #if submission.is_self:
        #    self._is_text_post = True
        #    self._post_was_serviced = True
        self._time_limit = timedelta(hours=0, minutes=time_limit_minutes)

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

    def candidate_submission_statement(self):
        # identify a possible submission statement

        # return early if these checks already ran, and ss is proper
        if self._submission_statement_validated:
            #print("\tsubmission statement validated")
            return True
        
        # 0.) Is the post is distinguished? If so, it is assumed to be made in "official capacity" and can be ignored by SSbot
        if self._submission.distinguished:
            self._submission_statement_validated = True 
            print("\tPost is distinguished - ignoring")
            return True

        # 1.) exempt text posts from this rule 
        # REMOVED. Why should text posts be excluded?
        #if self._submission.is_self:
        #    self._is_text_post = True 
        #    self._submission_statement_validated = True
        #    self._submission_statement = None
        #    # technically False, but True indicates everything is good, do not remove post
        #    #print("\tsubmission statement is self post; validated")
        #    return True

        # 2.) identify candidate submission statements. 
        # We need to find the SS bot's comment, and then look at the replies to it
        # submission.comments is a CommentForest (A forest of comments starts with multiple top-level comments.) meaning we can address top level comments and their replies
        ss_candidates = []
        for top_level_comment in self._submission.comments:
            if top_level_comment.author.name == cfg['CREDENTIALS']['username'] and "Submission Statement Request" in top_level_comment.body:
                # found the bot comment, take the replies as SS candidates

                self._submission.comments.replace_more() # Resolves the "More comments" text to get all comments
                for reply in top_level_comment.replies:
                    if reply.is_submitter:
                        ss_candidates.append(reply)

        # no SS
        if len(ss_candidates) == 0:
            self._submission_statement_validated = False
            self._submission_statement = None
            return False

        # one or more possible SS's
        if len(ss_candidates) == 1:
            self._submission_statement = ss_candidates[0]
            return True
        else:
            for candidate in ss_candidates:
                text = candidate.body
                text = text.lower().strip().split()

                # post author may have said "submission statement" in their comment, makes life easy
                if "submission" in text and "statement" in text:
                    self._submission_statement = candidate
                    break

                # otherwise, take the longest top level comment from OP
                if self._submission_statement:
                    if len(candidate.body) > len(self._submission_statement.body):
                        self._submission_statement = candidate
                else:
                    self._submission_statement = candidate
            return True

    def has_time_expired(self, time_limit):
        # True or False -- has the time expired to add a submission statement?
        return (self._created_time + timedelta(minutes=time_limit) < datetime.utcnow())

    def is_moderator_approved(self):
        print(f"Moderator approved? {self._submission.approved}\n\t")
        return self._submission.approved

    def is_post_removed(self):
        return self._submission.removed

    def refresh(self, reddit):
        self._submission = praw.models.Submission(reddit, id = self._submission.id)

    def submission_statement_validated(self, janitor_name):
        self._submission_statement_validated = False
        for comment in self._submission.comments:
            if comment and comment.author and comment.author.name and comment.body:
                if comment.author.name == janitor_name and "submission statement was provided" in comment.body:
                    self._submission_statement_validated = True 
                    break
        return self._submission_statement_validated

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

    def reply_to_post(self, text, pin=True, lock=False):
        posted_comment = self._submission.reply(text)
        posted_comment.mod.distinguish(sticky=pin)
        if lock:
            posted_comment.mod.lock()
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
                        user_agent = "linux:reddit_submission_bot:v0.1",                        
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
        print("Fetching new submissions " + datetime.utcnow().strftime("%Y-%m-%d, %H:%M:%S"))
        submissions = set()
        #newposts = self.subreddit.top(time_filter="day")
        newposts = self.subreddit.new()
            # we could use self.subreddit.new() but this would return 1000 posts and we won't get 1000 posts a day so this will give us a shorter list
            # was originally going to use subreddit.top but this doesn't return posts immediately when they're submitted, it takes time for Reddit to register them in the "top" list I suspect. So instead we use subreddit.new even though this will give a large list of results to process.
        for post in newposts:
            print(post.title)
            # we don't care about posts that have already been removed as the bot will not be able to override that
            # we do still want posts that moderators have approved, as the approval may be due to other reports
            if not (post.removed):
                submissions.add(Post(post))

        #self.submissions = submissions
        return submissions
    
    def update_submission_list(self):
        retrieved_submissions = self.fetch_submissions()
        self.submissions.union(retrieved_submissions) # We're adding to this list to ensure that we don't lose anything if there's a big influx of posts.
        #TODO - Prune submissions here to remove anything we've already validated, or that we've already removed. Is it as simple as the following? CHECK!
        for post in self.submissions:
            if post._submission_statement_validated or post.removed:
                self.submissions.remove(post)

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
            print(post._submission.title)
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
        #if self.sub_settings.report_old_posts:
        #    now = datetime.utcnow()
        #    for post in self.submissions:
        #        if post._created_time + timedelta(hours=12, minutes=0) < now:
        #            reason = "This post is over 12 hours old and has not been moderated. Please take a look!"
        #            post.report_post(reason)

    def handle_posts(self):
        print("Handling posts")
        self.refresh_posts()
        #self.prune_submissions()

        all_posts = self.submissions #.union(self.unmoderated)
        print("  "+str(len(all_posts)) + " submissions to check")
        for post in all_posts:
            print(f"  Checking post: {post._submission.title}\n\t{post._submission.permalink}...")

            if post.submission_statement_validated(self.username):
                # Already dealt with this one, skip
                print("\tSubmission statement already validated")
                continue

            if not post.serviced_by_janitor(self.username):
                print("\tNew post - requesting submission statement from user")
                # Here we have to request the submission statement from the author, and move on
                text = "Submission Statement Request\n\n" + self.sub_settings.submission_statement_request_text
                post.reply_to_post(text, pin=self.sub_settings.pin_submission_statement_request, lock=False)
                post._post_was_serviced = True
                continue

            else:
                print("\tSubmission statement already requested")    
                # We've interacted with this post before, so can check the SS          

            # So at this point the post hasn't had the SS validated.

            # First let's see if we need to do anything
            if post.has_time_expired(self.sub_settings.submission_statement_time_limit_minutes):
                print("\tTime has expired - taking action")

                # Remove original comment by the bot
                for top_level_comment in post._submission.comments:
                        if top_level_comment.author.name == cfg['CREDENTIALS']['username'] and "Submission Statement Request" in top_level_comment.body: 
                            #Do not use "is" as that compares in-memory objects to be the same object, use == for value comparison

                            # found the bot's request for a SS
                            # Remove all the comment's replies and delete the bot comment
                            post._submission.comments.replace_more() # Resolves the "More comments" text to get all comments
                            for comment in top_level_comment.replies.list():
                                # list(): Return a flattened list of all comments. (awesome - no recursion needed!)
                                comment.mod.remove()
                            top_level_comment.delete()
            
                # Check if there is a submission statement                
                if post.candidate_submission_statement():
                    print("\tPost has submission statement")                    

                    # does the submission statement have the required length?
                    #   no -> report or remove, depending on subreddit settings
                    #   yes -> remove bot comment and pin reason
                    if not len(post._submission_statement.body) >= self.sub_settings.submission_statement_minimum_char_length:
                        removal_note = "Submission statement is too short"
                        if self.sub_settings.remove_posts:
                            post.remove_post(self.sub_settings.removal_reason, removal_note)
                            print(f"\tRemoving post: \n\t\t{post._submission.title}\n\t\t{post._submission.permalink}")
                            print(f"\tReason: {removal_note}\n---\n")
                        else:                            
                            post.report_post(removal_note)
                            print(f"\tReporting post: \n\t\t{post._submission.title}\n\t\t{post._submission.permalink}")
                            print(f"\tReason: {removal_note}\n---\n")
                    else:
                        print(f"\tSS has proper length \n\t{post._submission.permalink}")

                        # We need to post the submission statement response. 
                        
                        post.reply_to_post(self.sub_settings.submission_statement_quote_text(post._submission_statement, self.sub_settings.submission_reply_spoiler), pin=self.sub_settings.pin_submission_statement_response, lock=True)
                        print(f"\tPinning submission statement: \n\t{post._submission.title}\n\t{post._submission.permalink}")

                        post._submission_statement_validated = True
                        print("\tSubmission statement validated")

                else:
                    print("\tPost does NOT have submission statement")
                    now = datetime.utcnow()

                    # Remove original comment by the bot
                    for top_level_comment in post._submission.comments:
                            if top_level_comment.author.name == cfg['CREDENTIALS']['username'] and "Submission Statement Request" in top_level_comment.body: 
                                #Do not use "is" as that compares in-memory objects to be the same object

                                # found the bot's request for a SS
                                # Remove all the comment's replies and delete the bot comment
                                post._submission.comments.replace_more() # Resolves the "More comments" text to get all comments
                                for comment in top_level_comment.replies.list():
                                    # list(): Return a flattened list of all comments. (awesome - no recursion needed!)
                                    comment.mod.remove()
                                top_level_comment.delete()

                               
                    # did a mod approve, or is it more than 1 day old? #DO WE CARE?
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
                print("\tTime has not expired - skipping post")
        print("  Done.")
                

def go():
    # Settings load
    fs = SSBSettings()
    jannie = Janitor(cfg['DEFAULT']['subreddit'])
    jannie.set_subreddit_settings(fs)
    while True:
        try:
            
            while True:
                # get submissions
                jannie.update_submission_list()
                # handle posts
                jannie.handle_posts()
                # every 5 min prune unmoderated
                time.sleep(60)

            # Wait 1 minute (60 seconds)
            time.sleep(60)

        except Exception as e:
            print(repr(e))
            print('Error on line {}'.format(sys.exc_info()[-1].tb_lineno), type(e).__name__, e)
            print("\n")
            print("Restarting...\n")
            time.sleep(5) #Pause to avoid a blocking loop

def run_forever():
    five_min = 60 * 5
    one_hr  = five_min * 12
    print("Running run_forever\n")
    while True:
        #try:
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
                time.sleep(60) #THIS WAS CHANGED FROM five_min
                jannie.prune_unmoderated()

                # every 1 hour prune submissions
                if counter == 0:
                    jannie.prune_submissions()
                counter = counter + 1
                counter = counter % 12

            # every hour, check all posts from the day
            # every 5 minutes, check unmoderated queue
       # except Exception as e:
           # print(repr(e))
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
    cfg = ConfigParser(interpolation = ExtendedInterpolation())
    cfg.read("submission-statement-bot.cfg")
    #run_once()
    #run_forever()
    go()