#!/usr/bin/python3

# Basic approach
# 1) User posts
# 2) Submission Bot (SB) posts a sticky telling the user they have x minutes to provide a submission statement of at least x length 
# 3) If the user doesn't comply, SB deletes the post and notifies the user via a removal reason and a new sticky comment
# 4) If the user does comply, SB deletes the sticky and posts a new sticky comment saying like "user has provided following reason: [...], please report post if this doesn't fit the sub"
# See flow diagrams on Github repo for more

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
# 5) A user deletes their post between the SS request and us checking it. Currently it remains on the list to be checked and is removed, but that does nothing in reality as it's already deleted. Can we deal with this more gracefully by checking for a "deleted" flag? Do we care?

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

# TODO: 
# DONE Why are we excluding text posts, need to include that again for future use.
# DONE Time limit seems to be set in multiple locations - need to walk through the logic to determine where it's getting taken from
# DONE Some of this code feels redundant, can we simplify? Remove any unused code 
# Document code below inline DONE, config file variables DONE, and github readme
# Validate flow DONE and capture this as a rewrite of the above section
# Edge cases

# Bug squashing TODO
# 1) DONE Bot seems to recheck old posts from before it was started. We don't want that. #Bug1 [Added in a post created timestamp check vs bot startup time]
# 2) DONE Reopened, still happening. Some issue exists with the way we're handling "checked" posts. They are appearing in the list again after already being checked/approved and are not reaching this point to remove them from checking again. Why? #Bug2 [Code was referencing "self" when setting checked/valid; in that context it was the adding those to the janitor and not to the post object]        
#   The submission is being marked as "checked", so that once it's been handled we aren't adding it to the janitor.submissions list again. But the problem occurs every other loop - because it's missing from the list, it gets re-added next time around, and then removed again, and then re-added etc. 
#   I think we need to hold a list of "handled" submissions so that we can remove them from the list. [janitor.checked_submissions set implemented, issue resolved]
# 3) DONE Submissions are being repeatedly added to the "to check" list whilst we're waiting for the timer to expire #Bug3 [Needed to re-implement __eq__ to allow union function to dedupe properly]
# 4) DONE "Actions taken" counter not working correctly, doesn't increment per action taken! #Bug4 [Indentation was wrong]

from configparser import ConfigParser, ExtendedInterpolation
from datetime import datetime, timedelta, timezone
import praw
import time
import traceback

###############################################################################
###
### Load Settings
###
###############################################################################

class SSBSettings():
    def __init__(self):
        self.subreddit = cfg['DEFAULT']['subreddit']
        #.encode('raw_unicode_escape').decode('unicode_escape') is required as ConfigParser will escape items such as "\n" to "\\n" and remove the newline functionality.
        # See here for why we've done it this way: https://stackoverflow.com/questions/1885181/how-to-un-escape-a-backslash-escaped-string/69772725#69772725
        self.removal_reason = str(cfg['TEXT']['removal_reason']).encode('raw_unicode_escape').decode('unicode_escape')
        if int(cfg['DEFAULT']['minutes_to_wait_for_submission_statement']) >= 1: # Enforce 1 minute minimum
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
        self._created_time = datetime.fromtimestamp(submission.created_utc, tz=timezone.utc)
        self._submission_statement_checked = False
        self._submission_statement_valid = False
        self._submission_statement = None
        self._post_was_serviced = False
        self.bot_text = "\n\n*" + str(cfg['TEXT']['bot_footer_text']).encode('raw_unicode_escape').decode('unicode_escape') + "*"
        self._time_limit = timedelta(hours=0, minutes=time_limit_minutes)

    # https://www.pythontutorial.net
    # Python automatically calls the __eq__ method of a class when you use the == operator to compare the instances of the class. 
    # By default, Python uses the is operator if you don’t provide a specific implementation for the __eq__ method; we don't want that as the objects are different but we care about comparing the Reddit submission to avoid #Bug3
    def __eq__(self, other):
        return self._submission.permalink == other._submission.permalink
    
    # https://www.pythontutorial.net
    # If a class overrides the __eq__ method (which we have), the objects of the class become unhashable by default.
    # To make the Person class hashable, we also need to implement the __hash__ method.
    def __hash__(self):
        return hash(self._submission.permalink)
    
    # https://www.pythontutorial.net
    # # Sometimes, it’s useful to have a string representation of an instance of a class. 
    # To customize the string representation of a class instance, the class needs to implement the __str__ magic method.
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
        return ((self._created_time + timedelta(minutes=time_limit)) < datetime.now(timezone.utc))

    def refresh(self, reddit):
        # refresh the post with the latest version from Reddit to ensure any status changes etc are captured
        self._submission = praw.models.Submission(reddit, id = self._submission.id)    

    def submission_statement_previously_validated(self, janitor_name):
        # have we already been through the validation process for this post's submission statement?
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
        self.checked_submissions = set()
        self.sub_settings = SSBSettings()
        self.startup_time = datetime.now(timezone.utc)
        self.run_start_time = datetime.now(timezone.utc)
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
        # If ant to check if post.removed or post.approved, in order to do this, must refresh running list. No need to check the queue or query again
        for post in self.submissions:
            post.refresh(self.reddit)


    def fetch_submissions(self, type="new"): 
        # get the latest list of submissions to the subreddit
        self.run_start_time = datetime.now(timezone.utc)
        print("Fetching new submissions. Time now is: " + datetime.now(timezone.utc).strftime("%Y-%m-%d, %H:%M:%S") + " UTC") #Bug1
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

        # Remove anything we've already seen #Bug2
        submissions = submissions - self.checked_submissions

        return submissions


    def update_submission_list(self): 
        # get the latest posts and remove any we don't need to deal with

        retrieved_submissions = self.fetch_submissions()
        self.submissions = self.submissions.union(retrieved_submissions) 
        # We're adding to this list to ensure that we don't lose anything if there's a big influx of posts. Union prevents duplicates, but as per #Bug3 this doesnt remove duplicate Reddit submissions. Why? 
        # Because items in self.submissions are objects of type Post, and each one of these is a different wrapper even if the actual Reddit content is the same. As such we have to utilise the "eq" method within the Post class to allow a comparison.

        # Refresh all the posts we have in the list to ensure their status is correct (primarily we're concerned about "removed")
        self.refresh_posts()

        # Iterate through the submissions list, mark anything we need to remove and then remove it.
        submissions_to_remove = set()
        for post in self.submissions:
            if post._submission.removed or post._submission_statement_checked: #Bug2
                submissions_to_remove.add(post)

        # Can't "live" remove items from self.submissions otherwise we'll hit a "Set changed size during iteration" error, so remove afterwards
        self.submissions = self.submissions - submissions_to_remove

    def remove_or_report_post(self, post, removal_reason):
        # depending on the config setting, we can remove the post, or just report it
        if self.sub_settings.remove_posts:
            post.remove_post(self.sub_settings.removal_reason, removal_reason)
            print(f"\tRemoving post: \n\t\t{post._submission.title}\n\t\t{post._submission.permalink}")
            print(f"\tReason: {removal_reason}\n---\n")
        else:                            
            post.report_post(removal_reason)
            print(f"\tReporting post: \n\t\t{post._submission.title}\n\t\t{post._submission.permalink}")
            print(f"\tReason: {removal_reason}\n---\n")
    
    def required_words_in_submission_statement(self, post):        
        # check for words from the config list within the ss
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
                        print("\tSS has proper length")

                        # We need to post the submission statement response.                         
                        post.reply_to_post(self.submission_statement_quote_text(post._submission_statement, self.sub_settings.submission_reply_spoiler), pin=self.sub_settings.pin_submission_statement_response, lock=True)                        
                        post._submission_statement_valid = True
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
                    
                    post._submission_statement_valid = False
                
                self.action_counter += 1 #Bug4                  
                self.checked_submissions.add(post)
                post._submission_statement_checked = True

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
                wait_time_from_config = int(cfg['DEFAULT']['bot_interval'])
                if wait_time_from_config > 30:
                    wait_time = wait_time_from_config
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

if __name__ == "__main__":
    cfg = ConfigParser(interpolation = ExtendedInterpolation(), converters={'list': lambda x: [i.strip() for i in x.split(',')] if len(x) > 0 else []})
    cfg.read("submission-statement-bot.cfg")
    #run_once()
    #run_forever()
    go()