"""Utilities for Instagram follower/following management."""

import json
from pathlib import Path
from typing import List, Set, Dict, Any, Optional
from loguru import logger


class InstagramUser:
    """Simple model for Instagram user."""
    def __init__(self, username: str, profile_url: str):
        self.username = username
        self.profile_url = profile_url

    def to_dict(self) -> Dict[str, Any]:
        return {
            "username": self.username,
            "profile_url": self.profile_url
        }


def load_users_from_file(file_path: Path) -> List[InstagramUser]:
    """
    Load users (followers or following) from a previously saved JSON file.

    Args:
        file_path: Path to the Instagram JSON file

    Returns:
        List of InstagramUser objects
    """
    if not file_path.exists():
        logger.warning(f"Users file not found: {file_path}")
        return []

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Determine if it's followers or following format
        users_data = data.get("followers", data.get("following", []))
        users = []

        for user_data in users_data:
            try:
                user = InstagramUser(
                    username=user_data.get("username"),
                    profile_url=user_data.get("profile_url")
                )
                users.append(user)
            except Exception as e:
                logger.warning(f"Could not parse user: {e}")
                continue

        logger.info(f"Loaded {len(users)} users from {file_path}")
        return users

    except Exception as e:
        logger.error(f"Failed to load users from {file_path}: {e}")
        return []


def find_new_users(
    new_users: List[InstagramUser],
    existing_users: List[InstagramUser]
) -> List[InstagramUser]:
    """
    Find users that are in new_users but not in existing_users.

    Args:
        new_users: List of newly scraped users
        existing_users: List of previously saved users

    Returns:
        List of InstagramUser objects that are new
    """
    # Create sets of usernames for quick lookup
    existing_usernames: Set[str] = set()
    existing_urls: Set[str] = set()

    for user in existing_users:
        if user.username:
            existing_usernames.add(user.username)
        if user.profile_url:
            existing_urls.add(user.profile_url)

    # Find new users
    new_user_list: List[InstagramUser] = []

    for user in new_users:
        is_new = True

        # Check by username first
        if user.username and user.username in existing_usernames:
            is_new = False

        # Also check by URL as fallback
        if is_new and user.profile_url and user.profile_url in existing_urls:
            is_new = False

        if is_new:
            new_user_list.append(user)

    logger.info(f"Found {len(new_user_list)} new users out of {len(new_users)} total")
    return new_user_list


def save_new_users(
    new_users: List[InstagramUser],
    output_dir: Path,
    scraped_at: Optional[str] = None,
    user_type: str = "users"
) -> Path:
    """
    Save new users to a separate JSON file.

    Args:
        new_users: List of new InstagramUser objects
        output_dir: Directory to save the file
        scraped_at: ISO timestamp for when the scrape happened
        user_type: Type of users (followers or following)

    Returns:
        Path to the saved file
    """
    from datetime import datetime

    if scraped_at is None:
        scraped_at = datetime.now().isoformat()

    output_dir.mkdir(parents=True, exist_ok=True)

    # Create filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"new_{user_type}_{timestamp}.json"

    # Convert users to dicts
    users_data = []
    for user in new_users:
        users_data.append(user.to_dict())

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "scraped_at": scraped_at,
            "new_users_count": len(new_users),
            f"new_{user_type}": users_data
        }, f, ensure_ascii=False, indent=2)

    logger.info(f"Saved {len(new_users)} new {user_type} to {output_file}")
    return output_file
