from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class Profile:
    username: str
    display_name: str
    bio: str
    post_count: str
    follower_text: str
    following_text: str
    is_private: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Post:
    shortcode: str
    caption: str
    timestamp: str
    like_text: str
    comment_text: str
    post_url: str
    media_type: str
    media_urls: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Follower:
    username: str
    display_name: str
    profile_url: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
