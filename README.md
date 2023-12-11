# Reddit Submission Statement Bot

This is a bot for Reddit, to manage "submission statements" on posts. These require that a user submits a justification for why the post meets the requirements of the subreddit (or that a user has read the rules for example), therefore reducing spam and other non-conforming content.

The variety of configuration options is described in more detail below, however at the "default" configuration the bot will run every 5 minutes and 
- check for new posts and request a submission statement
- look at posts where the 5 minute submission statement time has expired, check if the submission statement meets the 100 character limit, and either remove or approve them based on this criteria

The bot does not operate on historical posts, and will only manage posts submitted after the bot has started.

# Installation / Operation

### Set up a Reddit account
1. [Create a new Reddit account](https://www.reddit.com/register/) with an account name suitable for the bot, e.g. "subreddit-submission-bot".

2. Login into your a Reddit account which moderates your subreddit and has the ability to invite other moderators (or ask a moderator who can), and invite the bot to become a moderator with "Manage Posts and Comments" access. 

3. Log back into the bot’s account and accept the invitation.

5. Go to https://www.reddit.com/prefs/apps/ and select **Create an app**

6. Type a name for your app and choose **script**.

7. Write a short description of what your bot will be doing.

8. Set the `about URI` to this Github Repo URL (or any URL of your choice).

9. Set the `redirect URI` to "http://localhost:8080". 

10. Select **create app**.

11. Make note of both the client ID (the code underneath the "personal use script" subheading), and the client secret.

### Configure your hosting
1. It is assumed you will have a 24/7 available host, with a python environment. The bot will work most effectively if left running. Oracle's ["always free" tier](https://www.oracle.com/cloud/free/) is a suitable environment to use for this bot.

2. The bot has been tested on Python 3.10.12 and PRAW 7.7.1. See: [PRAW installation](https://praw.readthedocs.io/en/stable/getting_started/installation.html)

3. Obtain a copy of the bot's code - either select **Code** and then **Download Zip**, or **Clone** to your host via the HTTPS URL.

### Configure the Bot
1. Open **submission-statement-bot.cfg.example**

2. Set up the configuration as needed for your subreddit (see below for configuration options)

3. Save the file as **submission-statement-bot.cfg**

### Run the Bot

1. If you are in a linux environment, usage of a [screen](https://www.gnu.org/software/screen/manual/screen.html) is recommended.

2. Run the **submission-statement-bot.py** file in a terminal or command prompt; e.g. `python3 submission-statement-bot.py`

# Bot configuration options

`subreddit` name of your subreddit

`submission_statement_minimum_char_length` minimum character length of submission statement. A number from zero to anything you require.

`minutes_to_wait_for_submission_statement` number of minutes allowed for a user to respond with a submission statement. The minimum is 1 minute.

`pin_submission_statement_request` boolean (True/False) for whether we sticky the request for a submission statement.

`pin_submission_statement_response` boolean (True/False) for whether we sticky the submission statement response that the user has provided.

`remove_posts` boolean (True/False) for if we are removing a post or just reporting it. True = remove, False = report.

`use_spolier_tags` boolean (True/False) for if we should hide the text that was provided as a submission statement. Useful if the text gives away an unexpected outcome for example.

`bot_interval` number of seconds between each bot "run", minimum 30. Lower values will mean users wait a shorter period before receiving a request for a submission statement, but are more intensive on the host system.

`bot_remove_request` boolean (True/False) for if we should remove the "request for submission statement" comment that the bot makes

`required_words_in_submission_statement` a list of words, separated by commas, that must be in the submission statement. E.g. irtr, potato, banana

`removal_reason` the text that the bot uses in its comment when removing a post

`submission_statement_request` the text that the bot uses in its comment when requesting a submission statement

`bot_footer_text` the text displayed at the bottom of each comment from the bot, useful to explain that it is a bot and not a human

`username` Reddit user account name that the bot will use
`password` Reddit user password that the bot will use

`client_id` the "id" of the script application that was created on www.reddit.com/prefs/apps
`client_secret` the "secret" of the script application that was created on www.reddit.com/prefs/apps
