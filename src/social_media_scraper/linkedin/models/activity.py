from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class Activity(BaseModel):
    """Pydantic model representing a LinkedIn recent activity."""

    # Core identification
    linkedin_url: Optional[str] = None
    urn: Optional[str] = None

    # Type classification
    activity_type: Optional[str] = None  # original_post, repost, reaction
    reaction_type: Optional[str] = None  # like, celebrate, etc.

    # Content
    text: Optional[str] = None
    posted_date: Optional[str] = None

    # Engagement metrics
    reactions_count: Optional[int] = None
    comments_count: Optional[int] = None
    reposts_count: Optional[int] = None

    # Media
    image_urls: List[str] = Field(default_factory=list)
    video_url: Optional[str] = None
    article_url: Optional[str] = None

    # Original post info (for reposts and reactions)
    original_author_name: Optional[str] = None
    original_author_profile_url: Optional[str] = None
    original_post_urn: Optional[str] = None
    original_post_url: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

    def to_json(self, **kwargs) -> str:
        return self.model_dump_json(**kwargs)

    def __repr__(self) -> str:
        text_preview = self.text[:80] + "..." if self.text and len(self.text) > 80 else self.text
        return (
            f"<Activity\n"
            f"  Type: {self.activity_type}\n"
            f"  Text: {text_preview}\n"
            f"  Posted: {self.posted_date}\n"
            f"  Reactions: {self.reactions_count}>"
        )
