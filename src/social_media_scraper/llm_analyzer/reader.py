"""
Read scraped JSON data from data directory structure and aggregate content.
"""
import json
import os
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict
from pydantic import BaseModel

from loguru import logger


class ContentItem(BaseModel):
    """A single content item from any platform."""
    platform: str
    content_type: str  # post, note, profile, experience, education
    text: str
    timestamp: Optional[str] = None
    image_urls: List[str] = []          # Original URLs (kept for reference)
    local_image_paths: List[str] = []  # Locally downloaded paths
    date: Optional[datetime] = None


class AggregatedContent(BaseModel):
    """Aggregated content for an account."""
    account_name: str
    items: List[ContentItem]
    has_instagram: bool = False
    has_xiaohongshu: bool = False
    has_linkedin: bool = False


def _clean_filename(name: str) -> str:
    """Clean account name for use as directory filename."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)


class ContentAggregator:
    """Reads scraped JSON data and aggregates content for lead generation."""

    def __init__(
        self,
        data_dir: str,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        media_root: str = "media",
    ):
        self.data_dir = Path(data_dir)
        self.media_root = Path(media_root)
        self.from_date = None
        self.to_date = None

        if from_date:
            self.from_date = datetime.strptime(from_date, "%Y-%m-%d").date()
        if to_date:
            self.to_date = datetime.strptime(to_date, "%Y-%m-%d").date()

    def list_accounts(self) -> List[str]:
        """List all accounts in the data directory."""
        accounts = []
        for entry in os.scandir(self.data_dir):
            if entry.is_dir():
                # Check if it has at least one JSON file
                has_json = any(
                    f.suffix == ".json"
                    for f in Path(entry.path).iterdir()
                    if f.is_file()
                )
                if has_json:
                    accounts.append(entry.name)
        return sorted(accounts)

    def aggregate_account(self, account_name: str) -> Optional[AggregatedContent]:
        """Aggregate all content for a single account."""
        account_dir = self.data_dir / account_name
        if not account_dir.exists():
            logger.error(f"Account directory not found: {account_dir}")
            return None

        # Store current account name for locating local images
        self.current_account = account_name
        self.current_account_clean = _clean_filename(account_name)
        aggregated = AggregatedContent(account_name=account_name, items=[])
        items = []

        # Read Instagram
        instagram_file = account_dir / "instagram.json"
        if instagram_file.exists():
            with open(instagram_file, "r") as f:
                data = json.load(f)
                posts = data.get("data", [])
                if isinstance(posts, list):
                    for post in posts:
                        try:
                            item = self._parse_instagram_post(post)
                            if item and self._is_in_date_range(item):
                                items.append(item)
                        except Exception as e:
                            logger.warning(f"Failed to parse Instagram post: {e}")
                aggregated.has_instagram = True
                count = sum(1 for item in items if item.platform == "instagram")
                logger.debug(f"Loaded {count} Instagram posts for {account_name}")

        # Read Xiaohongshu
        xhs_file = account_dir / "xiaohongshu.json"
        if xhs_file.exists():
            with open(xhs_file, "r") as f:
                data = json.load(f)
                notes = data.get("data", [])
                xhs_items = []
                if isinstance(notes, list):
                    for note in notes:
                        try:
                            item = self._parse_xhs_note(note)
                            if item and self._is_in_date_range(item):
                                xhs_items.append(item)
                        except Exception as e:
                            logger.warning(f"Failed to parse Xiaohongshu note: {e}")
                items.extend(xhs_items)
                aggregated.has_xiaohongshu = True
                logger.debug(f"Loaded {len(xhs_items)} Xiaohongshu notes for {account_name}")

        # Read LinkedIn
        linkedin_file = account_dir / "linkedin.json"
        if linkedin_file.exists():
            with open(linkedin_file, "r") as f:
                data = json.load(f)
                profile = data.get("data", {})
                if isinstance(profile, dict):
                    linkedin_items = self._parse_linkedin_profile(profile)
                    # LinkedIn profile doesn't have date filtering - always include
                    items.extend(linkedin_items)
                aggregated.has_linkedin = True
                logger.debug(f"Loaded LinkedIn profile for {account_name}")

        aggregated.items = items

        # Sort by date
        aggregated.items.sort(key=lambda x: x.date or datetime.min)

        logger.info(
            f"Aggregated {len(aggregated.items)} total items for {account_name} "
            f"(Instagram={aggregated.has_instagram}, XHS={aggregated.has_xiaohongshu}, LinkedIn={aggregated.has_linkedin})"
        )

        return aggregated

    def _parse_instagram_post(self, post: Dict) -> Optional[ContentItem]:
        """Parse an Instagram post into a ContentItem."""
        text_parts = []
        if post.get("caption"):
            text_parts.append(post["caption"])
        if post.get("comment_text"):
            text_parts.append(post["comment_text"])

        text = "\n\n".join(text_parts).strip()
        if not text and not post.get("media_urls"):
            return None

        timestamp = post.get("timestamp")
        date_obj = None
        if timestamp:
            # Instagram timestamp is usually unix or ISO
            try:
                if isinstance(timestamp, (int, float)):
                    date_obj = datetime.fromtimestamp(timestamp)
                else:
                    date_obj = datetime.fromisoformat(str(timestamp))
            except (ValueError, TypeError):
                pass

        # Convert to naive datetime to avoid timezone comparison issues
        if date_obj and date_obj.tzinfo is not None:
            date_obj = date_obj.replace(tzinfo=None)

        # Find locally downloaded images if they exist
        # Instagram stores: media/{account_name}/instagram/{shortcode}/{filename}
        local_paths = []
        shortcode = post.get("shortcode")
        if shortcode and self.media_root.exists():
            instagram_media_dir = self.media_root / self.current_account_clean / "instagram" / shortcode
            if instagram_media_dir.exists():
                for ext in ["*.jpg", "*.jpeg", "*.png"]:
                    for img_path in instagram_media_dir.glob(ext):
                        local_paths.append(str(img_path))

        return ContentItem(
            platform="instagram",
            content_type="post",
            text=text,
            timestamp=timestamp,
            image_urls=post.get("media_urls", []),
            local_image_paths=local_paths,
            date=date_obj,
        )

    def _parse_xhs_note(self, note: Dict) -> Optional[ContentItem]:
        """Parse a Xiaohongshu note into a ContentItem."""
        text_parts = []
        if note.get("title"):
            text_parts.append(f"# {note['title']}")
        if note.get("desc"):
            text_parts.append(note["desc"])

        text = "\n\n".join(text_parts).strip()
        if not text and not note.get("image_list"):
            return None

        date = None
        # Try different date fields that might exist
        if note.get("last_update_time"):
            try:
                # XHS timestamp is milliseconds since epoch
                ts = int(note["last_update_time"]) / 1000
                date = datetime.fromtimestamp(ts)
            except (ValueError, TypeError):
                pass
        if date is None and note.get("upload_time"):
            try:
                # Upload time is string like "2025-07-22 22:25:40
                date = datetime.strptime(note["upload_time"], "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                pass

        # Convert to naive datetime to avoid timezone comparison issues
        if date and date.tzinfo is not None:
            date = date.replace(tzinfo=None)

        image_urls = []
        local_paths = []

        # Find locally downloaded images if they exist
        note_id = note.get("note_id")
        nickname = note.get("nickname", "")
        user_id = note.get("user_id", "")
        title = note.get("title", "")
        if note_id and self.media_root.exists():
            # Xiaohongshu stores: media/{account_name}/xiaohongshu/{nickname}_{user_id}/{title}_{note_id}/image_{index}.jpg
            xhs_dir = self.media_root / self.current_account_clean / "xiaohongshu" / f"{nickname}_{user_id}" / f"{title}_{note_id}"
            if xhs_dir.exists():
                for ext in ["*.jpg", "*.jpeg", "*.png"]:
                    for img_path in xhs_dir.glob(ext):
                        local_paths.append(str(img_path))

        # Still keep original URLs for reference
        for img in note.get("image_list", []):
            if isinstance(img, dict) and img.get("url"):
                image_urls.append(img["url"])
            elif isinstance(img, str):
                image_urls.append(img)

        return ContentItem(
            platform="xiaohongshu",
            content_type="note",
            text=text,
            timestamp=note.get("last_update_time") or note.get("upload_time"),
            image_urls=image_urls,
            local_image_paths=local_paths,
            date=date,
        )

    def _parse_linkedin_profile(self, profile: Dict) -> List[ContentItem]:
        """Parse a LinkedIn profile into ContentItems."""
        items = []

        # About summary
        if profile.get("about"):
            items.append(ContentItem(
                platform="linkedin",
                content_type="profile",
                text=f"# About\n\n{profile['about']}",
            ))

        # Experiences
        for exp in profile.get("experiences", []):
            text_parts = []
            title = exp.get("title", "")
            company = exp.get("company", "")
            date_range = f"{exp.get('start_date', '')} - {exp.get('end_date', '')}"
            text_parts.append(f"# Experience: {title} at {company} ({date_range})")
            if exp.get("description"):
                text_parts.append(exp["description"])
            items.append(ContentItem(
                platform="linkedin",
                content_type="experience",
                text="\n\n".join(text_parts),
            ))

        # Education
        for edu in profile.get("education", []):
            text_parts = []
            school = edu.get("school", "")
            degree = edu.get("degree", "")
            date_range = f"{edu.get('start_date', '')} - {edu.get('end_date', '')}"
            text_parts.append(f"# Education: {degree} at {school} ({date_range})")
            if edu.get("description"):
                text_parts.append(edu["description"])
            items.append(ContentItem(
                platform="linkedin",
                content_type="education",
                text="\n\n".join(text_parts),
            ))

        return items

    def _is_in_date_range(self, item: ContentItem) -> bool:
        """Check if item is within the configured date range."""
        if not self.from_date and not self.to_date:
            return True

        if not item.date:
            # If no date, include it anyway (mostly for older content)
            return True

        item_date = item.date.date()

        if self.from_date and item_date < self.from_date:
            return False
        if self.to_date and item_date > self.to_date:
            return False

        return True
