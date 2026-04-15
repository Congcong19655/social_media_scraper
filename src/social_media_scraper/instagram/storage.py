from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path

from social_media_scraper.instagram.models import Post, Profile


def default_output_path(username: str) -> Path:
    return Path("data") / f"{username}.json"


def write_scrape_result(output_path: Path, profile: Profile, posts: list[Post]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "profile": profile.to_dict(),
        "posts": [post.to_dict() for post in posts],
    }
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def download_post_media(posts: list[Post], media_dir: Path) -> int:
    media_dir.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    for post in posts:
        post_dir = media_dir / post.shortcode
        post_dir.mkdir(parents=True, exist_ok=True)
        unique_media_urls = _dedupe_urls(post.media_urls)
        for index, media_url in enumerate(unique_media_urls, start=1):
            filename = _media_filename(post.shortcode, index, media_url)
            destination = post_dir / filename
            if destination.exists():
                continue
            urllib.request.urlretrieve(media_url, destination)
            downloaded += 1
    return downloaded


def _media_filename(shortcode: str, index: int, media_url: str) -> str:
    parsed = urllib.parse.urlparse(media_url)
    suffix = Path(parsed.path).suffix or ".bin"
    return f"{shortcode}-{index}{suffix}"


def _dedupe_urls(urls: list[str]) -> list[str]:
    unique_urls: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)
    return unique_urls
