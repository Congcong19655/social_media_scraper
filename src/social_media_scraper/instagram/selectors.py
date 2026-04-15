from __future__ import annotations

PROFILE_POST_LINKS = "a[href*='/p/'], a[href*='/reel/']"
FEED_POST_LINKS = "article a[href*='/p/'], article a[href*='/reel/']"
PROFILE_HEADER = "header"
PROFILE_PRIVATE_MARKERS = (
    "This Account is Private",
    "This account is private",
)
LOGIN_PATH_SNIPPETS = (
    "/accounts/login",
    "/challenge/",
    "/checkpoint/",
)

# Instagram follower/following list selectors
PROFILE_FOLLOWERS_LINK = "a[href*='/followers/']"
PROFILE_FOLLOWING_LINK = "a[href*='/following/']"
FOLLOWER_MODAL = "div[role='dialog']"
# More general selector - any link-containing item in the dialog
FOLLOWER_ITEM = "div[role='dialog'] li"
FOLLOWER_ITEM_ALT = "div[role='dialog'] div[class*='user']"
FOLLOWER_ITEM_ALT2 = "div[role='dialog'] div > div"
FOLLOWER_USERNAME_LINK = "a[href^='/']"
FOLLOWER_DISPLAY_NAME = "span"
