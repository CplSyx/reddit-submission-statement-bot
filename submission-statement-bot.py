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
#      DONE What if we get an influx of posts and we can't deal with them all? At the moment every single post is reprocessed fully. We need to prune the "submission" list to remove anything that the bot has already validated before it hits handle_posts - ideally in update_submission_list
# 4) Keyword requirement - IRTR etc.
#      DONE Implement a list of required words in the submission statement to avoid bots gaming the system and that people read the rules etc.

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
# TODO: Remove any unused code 

# Bug squashing TODO
# 1) DONE Bot seems to recheck old posts from before it was started. We don't want that. #Bug1
# 2) Some issue exists with the way we're handling "checked" posts. They are appearing in the list again after already being checked/approved and are not reaching this point to remove them from checking again. Why? #Bug2


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

from configparser import ConfigParser, ExtendedInterpolation
from datetime import datetime, timedelta, timezone
import praw
import time
import traceback

###############################################################################
###
### Helper class -- settings base class
###
###############################################################################

class SubredditSettings:
    def __init__(self):
        # list of flair text, in lower case
        self.low_effort_flair = []
        self.removal_reason = str(cfg['TEXT']['removal_reason']).encode('raw_unicode_escape').decode('unicode_escape')
        self.submission_statement_request_text = str(cfg['TEXT']['submission_statement_request']).encode('raw_unicode_escape').decode('unicode_escape')        
        if int(cfg['DEFAULT']['minutes_to_wait_for_submission_statement']) >= 1:
            self.submission_statement_time_limit_minutes = int(cfg['DEFAULT']['minutes_to_wait_for_submission_statement']) 
        else:
            self.submission_statement_time_limit_minutes = 1     
        self.submission_statement_minimum_char_length = int(cfg['DEFAULT']['submission_statement_minimum_char_length'])
        self.report_insufficient_length = True
        self.remove_posts = cfg['DEFAULT'].getboolean('remove_posts')
        self.pin_submission_statement_request = cfg['DEFAULT'].getboolean('pin_submission_statement_request')
        self.pin_submission_statement_response = cfg['DEFAULT'].getboolean('pin_submission_statement_response')
        self.required_words = cfg['DEFAULT'].getlist('required_words_in_submission_statement')
        self.remove_request_comment = cfg['DEFAULT'].getboolean('bot_remove_request')

###############################################################################
###
### Load Settings
###
###############################################################################

class SSBSettings():#(SubredditSettings):
    def __init__(self):
        #super().__init__() #TODO Why? We can just use this class can't we? CONFIRM IF WORKING AS SubredditSettings CURRENTLY COMMENTED OUT

        self.subreddit = cfg['DEFAULT']['subreddit']
        #.encode('raw_unicode_escape').decode('unicode_escape') is required as ConfigParser will escape items such as "\n" to "\\n" and remove the newline functionality.
        # See here for why we've done it this way: https://stackoverflow.com/questions/1885181/how-to-un-escape-a-backslash-escaped-string/69772725#69772725
        self.removal_reason = str(cfg['TEXT']['removal_reason']).encode('raw_unicode_escape').decode('unicode_escape')
        if int(cfg['DEFAULT']['minutes_to_wait_for_submission_statement']) >= 1:
            self.submission_statement_time_limit_minutes = int(cfg['DEFAULT']['minutes_to_wait_for_submission_statement']) 
        else:
            self.submission_statement_time_limit_minutes = 1   
        self.submission_statement_request_text = str(cfg['TEXT']['submission_statement_request']).encode('raw_unicode_escape').decode('unicode_escape')
        self.submission_statement_minimum_char_length = int(cfg['DEFAULT']['submission_statement_minimum_char_length'])
        self.report_insufficient_length = True
        self.remove_posts = cfg['DEFAULT'].getboolean('remove_posts')
        self.pin_submission_statement_request = cfg['DEFAULT'].getboolean('pin_submission_statement_request')
        self.pin_submission_statement_response = cfg['DEFAULT'].getboolean('pin_submission_statement_response')
        self.submission_reply_spoiler = cfg['DEFAULT'].getboolean('use_spolier_tags')
        self.required_words = cfg['DEFAULT'].getlist('required_words_in_submission_statement')
        self.remove_request_comment = cfg['DEFAULT'].getboolean('bot_remove_request')
        


###############################################################################
###
### Helper class -- wrapper for PRAW "submissions"
### https://praw.readthedocs.io/en/stable/code_overview/models/submission.html
###
###############################################################################

class Post:
    def __init__(self, submission, time_limit_minutes=30):
        self._submission = submission
        self._created_time = datetime.fromtimestamp(submission.created_utc, tz=timezone.utc)#datetime.utcfromtimestamp(submission.created_utc)
        self._submission_statement_checked = False
        self._submission_statement_valid = False
        self._submission_statement = None
        self._post_was_serviced = False
        self.bot_text = "\n\n*" + str(cfg['TEXT']['bot_footer_text']).encode('raw_unicode_escape').decode('unicode_escape') + "*"
        self._time_limit = timedelta(hours=0, minutes=time_limit_minutes)

    def __eq__(self, other):
        return self._submission.permalink == other._submission.permalink

    def __hash__(self):
        return hash(self._submission.permalink)

    def __str__(self):
        return f"{self._submission.permalink} | {self._submission.title}"

    def candidate_submission_statement(self):
        # identify a possible submission statement
        
        # Is the post is distinguished? If so, it is assumed to be made in "official capacity" and can be ignored by SSbot
        if self._submission.distinguished:
            self._submission_statement_checked = True 
            self._submission_statement_valid = True # We're assuming this given it's a mod post.
            print("\tPost is distinguished - ignoring")
            return True
        
        # Identify candidate submission statements. 
        # We need to find the SS bot's comment, and then look at the replies to it
        # submission.comments is a CommentForest (A forest of comments starts with multiple top-level comments.) meaning we can address top level comments and their replies
        ss_candidates = []
        for top_level_comment in self._submission.comments:
            if top_level_comment.author is not None and top_level_comment.author.name == cfg['CREDENTIALS']['username'] and "Submission Statement Request" in top_level_comment.body:
                # found the bot comment, take the replies as SS candidates

                self._submission.comments.replace_more() # Resolves the "More comments" text to get all comments
                for reply in top_level_comment.replies:
                    if reply.is_submitter:
                        ss_candidates.append(reply)

        # no SS
        if len(ss_candidates) == 0:
            self._submission_statement_checked = False
            self._submission_statement_valid = False
            self._submission_statement = None
            return False

        # one or more possible SS's
        if len(ss_candidates) == 1:
            self._submission_statement = ss_candidates[0]
            return True
        else:
            for candidate in ss_candidates:
                
                # Create a list of words in the comment
                text = candidate.body
                text = text.lower().strip().split()

                # Check the comment for the words "submission" and "statement"
                # (the author may have said "submission statement" in their comment, makes life easy)
                if "submission" in text and "statement" in text:
                    self._submission_statement = candidate
                    break

                # otherwise, take the longest reply comment from OP
                if self._submission_statement:
                    if len(candidate.body) > len(self._submission_statement.body):
                        self._submission_statement = candidate
                else:
                    self._submission_statement = candidate
            return True

    def has_time_expired(self, time_limit):
        # True or False -- has the time expired to add a submission statement?
        return ((self._created_time + timedelta(minutes=time_limit)) < datetime.now(timezone.utc))#datetime.utcnow())

    def is_moderator_approved(self):
        print(f"\tModerator approved? {self._submission.approved}")
        return self._submission.approved

    def refresh(self, reddit):
        self._submission = praw.models.Submission(reddit, id = self._submission.id)    

    def submission_statement_previously_validated(self, janitor_name):
        if self._submission_statement_valid == True:
            return True
        
        self._submission_statement_valid = False
        for comment in self._submission.comments:
            if comment and comment.author and comment.author.name and comment.body:
                if comment.author.name == janitor_name and "submission statement was provided" in comment.body:
                    self._submission_statement_valid = True 
                    self._submission_statement_checked = True
                    break
        return self._submission_statement_valid

    def serviced_by_janitor(self, janitor_name):
        # Serviced means the janitor has taken some kind of action - that has resulted in leaving a comment behind.
        
        if self._post_was_serviced:
            return True

        self._post_was_serviced = False
        for reply in self._submission.comments:
            if reply and reply.author and reply.author.name:
                if reply.author.name == janitor_name:
                    self._post_was_serviced = True 
                    break
        return self._post_was_serviced


    def report_post(self, reason):
        self._submission.report(reason)

    def report_submission_statement(self, reason):
        self._submission_statement.report(reason)

    def reply_to_post(self, text, pin=True, lock=False):
        posted_comment = self._submission.reply(text + self.bot_text)
        posted_comment.mod.distinguish(sticky=pin)
        if lock:
            posted_comment.mod.lock()


    def remove_post(self, reason, note):
        self._submission.mod.remove(spam=False, mod_note=note)
        formatted_note = "\n\n(Removal reason: "+ note +")"
        removal_comment = self._submission.reply(reason + formatted_note + self.bot_text)
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
                        user_agent = "linux:reddit_submission_bot:v1.0",                        
                        username = cfg['CREDENTIALS']['username'],
                        password = cfg['CREDENTIALS']['password']
        )
        self.username = cfg['CREDENTIALS']['username']
        self.subreddit = self.reddit.subreddit(subreddit)
        self.mod = self.subreddit.mod
        self.submissions = set()
        self.unmoderated = set()
        self.sub_settings = SSBSettings()#SubredditSettings()
        self.startup_time = datetime.now(timezone.utc)#datetime.utcnow()
        self.run_start_time = datetime.now(timezone.utc)#datetime.utcnow()
        self.action_counter = 0

    def set_subreddit_settings(self, sub_settings):
        self.sub_settings = sub_settings

    def submission_statement_quote_text(self, ss, spoilers):
        # Construct the quoted message, by quoting OP's submission statement

        verbiage = f"The following submission statement was provided by u/{ss.author}:\n\n---\n\n"
        #WARNING: the text phrase "submission statement was provided" is used as a verification of a bot reply later in the code (in the "submission_statement_previously_validated" function). Do not change the above line in isolation.
         
        if(spoilers):
            quote_text = ss.body.replace("\n\n", "!<\n\n>!") # Need to be able to handle line breaks in the Reddit format, as spoiler tags don't carry over.
            verbiage = verbiage + ">!" + quote_text + "!<"
        else:
            verbiage = verbiage + ss.body
        verbiage = verbiage + f"\n\n---\n\n Does this explain the post? If not, please report and a moderator will review. \n\n"
        return verbiage


    def refresh_posts(self):
        # want to check if post.removed or post.approved, in order to do this,
        # must refresh running list. No need to check the queue or query again
        #
        # this method is necessary because Posts dont have a Reddit property
        for post in self.submissions:
            post.refresh(self.reddit)


    def fetch_submissions(self, type="new"):
        self.run_start_time = datetime.now(timezone.utc)#datetime.utcnow()
        print("Fetching new submissions. Time now is: " + datetime.now(timezone.utc).strftime("%Y-%m-%d, %H:%M:%S") + " UTC") #Bug1 #datetime.utcnow().strftime("%Y-%m-%d, %H:%M:%S") + " UTC") #Bug1
        submissions = set()
        if (type == "new") :
            newposts = self.subreddit.new()
            # Was originally going to use subreddit.top but this doesn't return posts immediately when they're submitted for some reason - it takes time for Reddit to register them in the "top" list I suspect. So instead we use subreddit.new even though this will give a larger list of results to process.
            # Possibility we could limit the number of posts retrieved, but how would we know where to put that limit? Default is 1000 posts. As such adding this as the default choice if nothing is specified.
        else :
            newposts = self.subreddit.top(time_filter="day")

        # Add each post into our wrapper class
        startup_timestamp = time.mktime(self.startup_time.timetuple())
        for post in newposts:
            if post.created_utc > startup_timestamp: # Ignore posts created before the bot was started
                submissions.add(Post(post))

        return submissions


    def update_submission_list(self):
        retrieved_submissions = self.fetch_submissions()
        self.submissions = self.submissions.union(retrieved_submissions) # We're adding to this list to ensure that we don't lose anything if there's a big influx of posts. Union prevents duplicates.

        # Refresh all the posts we have in the list to ensure their status is correct (primarily we're concerned about "removed")
        self.refresh_posts()

        # Iterate through the submissions list, mark anything we need to remove and then remove it.
        submissions_to_remove = set()
        for post in self.submissions:
            if post._submission.removed or post._submission_statement_checked: #Bug2
                submissions_to_remove.add(post)

        # Can't "live" remove items from self.submissions otherwise we'll hit a "Set changed size during iteration" error, so remove afterwards
        self.submissions = self.submissions.difference(submissions_to_remove)

    def remove_or_report_post(self, post, removal_reason):
        if self.sub_settings.remove_posts:
            post.remove_post(self.sub_settings.removal_reason, removal_reason)
            print(f"\tRemoving post: \n\t\t{post._submission.title}\n\t\t{post._submission.permalink}")
            print(f"\tReason: {removal_reason}\n---\n")
        else:                            
            post.report_post(removal_reason)
            print(f"\tReporting post: \n\t\t{post._submission.title}\n\t\t{post._submission.permalink}")
            print(f"\tReason: {removal_reason}\n---\n")
    
    def required_words_in_submission_statement(self, post):        
        if len(self.sub_settings.required_words) > 0:
            for word in self.sub_settings.required_words:                            
                if word not in post._submission_statement.body:
                    return False
            print(f"\tSS has required word(s) \n\t{post._submission.permalink}")
        return True

    def handle_posts(self):
        print("Handling posts")
        
        print("  "+str(len(self.submissions)) + " submissions to check")
        for post in self.submissions:
            print(f"  Checking post: {post._submission.title}\n\t{post._submission.permalink}...")

            if post.submission_statement_previously_validated(self.username): 
                # Skip posts that we've already validated
                print("\tSubmission statement already validated")
                continue

            if not post.serviced_by_janitor(self.username):
                print("\tNew post - requesting submission statement from user")
                # Here we have to request the submission statement from the author, and move on
                text = "###Submission Statement Request\n\n" + self.sub_settings.submission_statement_request_text
                post.reply_to_post(text, pin=self.sub_settings.pin_submission_statement_request, lock=False)
                post._post_was_serviced = True
                self.action_counter += 1
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
                        if top_level_comment.author is not None and top_level_comment.author.name == cfg['CREDENTIALS']['username'] and "Submission Statement Request" in top_level_comment.body: 
                            # Do not use "is" as that compares in-memory objects to be the same object, use == for value comparison

                            # found the bot's request for a SS
                            # Remove all the comment's replies and delete the bot comment
                            post._submission.comments.replace_more() # Resolves the "More comments" text to get all comments
                            for comment in top_level_comment.replies.list():
                                # .list(): Return a flattened list of all comments. (awesome - no recursion needed!)
                                comment.mod.remove()
                            top_level_comment.delete()
            
                # Check if there is a submission statement                
                if post.candidate_submission_statement():
                    print("\tPost has submission statement")                    

                    # Does the submission statement have the required length?
                    # If not, report or remove depending on subreddit settings
                    if not len(post._submission_statement.body) >= self.sub_settings.submission_statement_minimum_char_length:
                        removal_note = "Submission statement is too short"
                        self.remove_or_report_post(post, removal_note)
                                            
                    # Check for required words in the post if there are any set in the config
                    # If one of the words isn't found, remove/report the post depending on subreddit settings
                    elif not self.required_words_in_submission_statement(post):
                        removal_note = "Submission statement does not contain the requisite words"
                        self.remove_or_report_post(post, removal_note)
                                            
                    else:                        
                        print(f"\tSS has proper length \n\t{post._submission.permalink}")

                        # We need to post the submission statement response.                         
                        post.reply_to_post(self.submission_statement_quote_text(post._submission_statement, self.sub_settings.submission_reply_spoiler), pin=self.sub_settings.pin_submission_statement_response, lock=True)                        
                        self._submission_statement_valid = True
                        print("\tSubmission statement validated")

                else:
                    print("\tPost does NOT have submission statement")

                    if self.sub_settings.remove_request_comment:
                        # Remove original comment by the bot
                        for top_level_comment in post._submission.comments:
                                if top_level_comment.author is not None and top_level_comment.author.name == cfg['CREDENTIALS']['username'] and "Submission Statement Request" in top_level_comment.body: 
                                    #Do not use "is" as that compares in-memory objects to be the same object, use == to compare values

                                    # Found the bot's request for a SS
                                    # Remove all the comment's replies and delete the bot comment
                                    post._submission.comments.replace_more() # Resolves the "More comments" text to get all comments
                                    for comment in top_level_comment.replies.list():
                                        # list(): Return a flattened list of all comments. (awesome - no recursion needed!)
                                        comment.mod.remove()
                                    top_level_comment.delete()

                    # Report / Remove                
                    removal_note = "No submission statement provided"                               
                    if self.sub_settings.remove_posts:
                        post.remove_post(self.sub_settings.removal_reason, removal_note)
                        print(f"\tRemoving post: \n\t{post._submission.title}\n\t{post._submission.permalink}")
                        print(f"\tReason: {removal_note}\n---\n")   
                    else:
                        post.report_post(removal_note)
                        print(f"\tReporting post: \n\t{post._submission.title}\n\t{post._submission.permalink}")
                        print(f"\tReason: {removal_note}\n---\n")
                    
                    self._submission_statement_valid = False
                    self.action_counter += 1

                self._submission_statement_checked = True   
            else:
                print("\tTime has not expired - skipping post")
            

        print("  Done in " + str(datetime.now(timezone.utc) - self.run_start_time) + ".")
        print(str(self.action_counter) + " actions taken. Bot runtime " + str(datetime.now(timezone.utc) - self.startup_time) + ".")
        #print("  Done in " + str(datetime.utcnow() - self.run_start_time) + ".")
        #print(str(self.action_counter) + " actions taken. Bot runtime " + str(datetime.utcnow() - self.startup_time) + ".")

###############################################################################
###
### Script 
###
###############################################################################               

def go():
    
    # Init Janitor
    print("Setting subreddit: "+ cfg['DEFAULT']['subreddit'])
    jannie = Janitor(cfg['DEFAULT']['subreddit'])

    # Settings load
    fs = SSBSettings()
    jannie.set_subreddit_settings(fs)
    print("Settings loaded")
    while True:
        try:
            
            while True:
                print("- - -")   

                # get submissions
                jannie.update_submission_list()

                # handle posts
                jannie.handle_posts()
                 
                # Wait (min 30 seconds)
                if int(cfg['DEFAULT']['bot_interval']) > 30:
                    wait_time = int(cfg['DEFAULT']['bot_interval'])
                else:
                    wait_time = 30
                print("Waiting " + str(wait_time) +" seconds")
                time.sleep(wait_time) 

        except Exception as e:
            print("\n---ERROR---\n")
            print(repr(e))
            traceback.print_exc()
            print("\n")
            print("Restarting in 10 seconds...\n")
            time.sleep(10) #Pause 10s to avoid a rapid/blocking loop


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
                print("\r\n")      
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
            print("\r\n")
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
    cfg = ConfigParser(interpolation = ExtendedInterpolation(), converters={'list': lambda x: [i.strip() for i in x.split(',')] if len(x) > 0 else []})
    cfg.read("submission-statement-bot.cfg")
    #run_once()
    #run_forever()
    go()