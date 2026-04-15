from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from social_media_scraper.instagram.browser import BrowserSessionError, authenticated_context
from social_media_scraper.instagram.models import Post, Profile, Follower
from social_media_scraper.instagram.selectors import (
    FEED_POST_LINKS,
    PROFILE_HEADER,
    PROFILE_POST_LINKS,
    PROFILE_PRIVATE_MARKERS,
    PROFILE_FOLLOWERS_LINK,
    PROFILE_FOLLOWING_LINK,
    FOLLOWER_MODAL,
    FOLLOWER_ITEM,
    FOLLOWER_ITEM_ALT,
    FOLLOWER_ITEM_ALT2,
    FOLLOWER_USERNAME_LINK,
    FOLLOWER_DISPLAY_NAME,
)


class ScrapeError(RuntimeError):
    """Raised when scraping cannot continue safely."""


def scrape_profile(
    username: str,
    limit: int,
    session_dir: Path,
    from_date: date | None = None,
    to_date: date | None = None,
    *,
    headless: bool = False,
) -> tuple[Profile, list[Post]]:
    with authenticated_context(session_dir, headless=headless) as context:
        page = context.pages[0] if context.pages else context.new_page()
        profile_url = f"https://www.instagram.com/{username.strip().strip('/')}/"
        page.goto(profile_url, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        if _is_login_or_checkpoint(page.url):
            raise BrowserSessionError("Instagram redirected to login or checkpoint while opening the target profile.")

        html = page.content()
        if _profile_not_found(html):
            raise ScrapeError(f"Profile `{username}` was not found.")

        profile = parse_profile_html(html, username)
        if profile.is_private and not _has_visible_posts(page):
            raise ScrapeError(f"Profile `{username}` is not visible to the logged-in session.")

        posts = collect_and_process_posts(context, page, limit, from_date, to_date)
        return profile, posts


def collect_post_urls(page, limit: int) -> list[str]:
    seen: list[str] = []
    stagnant_rounds = 0
    while len(seen) < limit and stagnant_rounds < 5:
        urls = page.locator(PROFILE_POST_LINKS).evaluate_all(
            """
            elements => elements
                .map(element => element.href)
                .filter(Boolean)
            """
        )
        normalized = []
        for url in urls:
            parsed = urlparse(url)
            if "/p/" in parsed.path or "/reel/" in parsed.path:
                normalized.append(f"{parsed.scheme}://{parsed.netloc}{parsed.path}")
        unique = list(dict.fromkeys(normalized))
        if len(unique) == len(seen):
            stagnant_rounds += 1
        else:
            stagnant_rounds = 0
            seen = unique
        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(1200)
    return seen[:limit]


def collect_and_process_posts(
    context,
    page,
    limit: int,
    from_date: date | None,
    to_date: date | None,
    post_selector: str = PROFILE_POST_LINKS,
) -> list[Post]:
    """Incrementally collect and process posts with date filtering and early stopping."""
    seen_urls: set[str] = set()
    posts: list[Post] = []
    stagnant_rounds = 0
    early_stop = False

    while len(posts) < limit and stagnant_rounds < 5 and not early_stop:
        # Get current visible URLs
        urls = page.locator(post_selector).evaluate_all(
            """
            elements => elements
                .map(element => element.href)
                .filter(Boolean)
            """
        )
        normalized = []
        for url in urls:
            parsed = urlparse(url)
            if "/p/" in parsed.path or "/reel/" in parsed.path:
                normalized_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                if normalized_url not in seen_urls:
                    normalized.append(normalized_url)
                    seen_urls.add(normalized_url)

        if len(normalized) == 0:
            stagnant_rounds += 1
        else:
            stagnant_rounds = 0

        # Process each new URL
        for post_url in normalized:
            if len(posts) >= limit:
                break

            # Extract timestamp first (lightweight operation)
            post_date = extract_post_date(context, post_url)

            # Check date bounds
            if post_date is not None:
                # Post is newer than to_date → skip
                if to_date is not None and post_date > to_date:
                    continue
                # Post is older than from_date → stop early (all remaining will be older)
                if from_date is not None and post_date < from_date:
                    early_stop = True
                    break

            # If we get here, post is within range → do full scrape
            post = scrape_post(context, post_url)

            # Double-check date after full scrape (in case lightweight extraction failed)
            include_post = True
            if post.timestamp:
                try:
                    post_dt = date.fromisoformat(post.timestamp[:10])
                    if from_date is not None and post_dt < from_date:
                        include_post = False
                        early_stop = True
                    if to_date is not None and post_dt > to_date:
                        include_post = False
                except ValueError:
                    pass  # Include if parsing fails

            if include_post:
                posts.append(post)
            elif from_date is not None and early_stop:
                break

        # Scroll for more posts if not stopping early
        if not early_stop:
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(1200)

    return posts


def extract_post_date(context, post_url: str) -> date | None:
    """Lightweight extraction to get just the post date."""
    page = context.new_page()
    try:
        normalized_post_url = _normalize_post_url(post_url)
        page.goto(normalized_post_url, wait_until="domcontentloaded")
        page.wait_for_timeout(400)  # Faster timeout for just timestamp extraction
        html = page.content()
        soup = BeautifulSoup(html, "html.parser")
        timestamp_str = _extract_timestamp(soup)
        if timestamp_str:
            try:
                # First 10 chars are YYYY-MM-DD in ISO format
                return date.fromisoformat(timestamp_str[:10])
            except ValueError:
                pass
        return None
    finally:
        page.close()


def scrape_post(context, post_url: str) -> Post:
    page = context.new_page()
    try:
        normalized_post_url = _normalize_post_url(post_url)
        page.goto(normalized_post_url, wait_until="domcontentloaded")
        page.wait_for_timeout(1000)
        post = parse_post_html(page.content(), normalized_post_url)
        post.media_urls = _extract_post_media_urls(page, normalized_post_url, post.media_type)
        return post
    finally:
        page.close()


def parse_profile_html(html: str, fallback_username: str) -> Profile:
    soup = BeautifulSoup(html, "html.parser")
    header = soup.select_one(PROFILE_HEADER)
    if header is None:
        raise ScrapeError("Instagram profile header could not be found. The DOM may have changed.")

    username = _clean_text(_first_text(header, ["h2", "h1"])) or fallback_username
    display_name = _clean_text(_first_text(header, ["section h1", "div h1", "span"]))
    description = _meta_content(soup, "description")
    bio = _extract_bio(header, username)
    post_count, follower_text, following_text = _extract_counts(header, description)
    page_text = soup.get_text(" ", strip=True)
    is_private = any(marker in page_text for marker in PROFILE_PRIVATE_MARKERS)

    return Profile(
        username=username,
        display_name=display_name,
        bio=bio,
        post_count=post_count,
        follower_text=follower_text,
        following_text=following_text,
        is_private=is_private,
    )


def parse_post_html(html: str, post_url: str) -> Post:
    soup = BeautifulSoup(html, "html.parser")
    shortcode = _extract_shortcode(post_url)
    description = _meta_content(soup, "description")
    title = _meta_property(soup, "og:title")
    caption = _extract_caption(soup, description, title)
    timestamp = _extract_timestamp(soup)
    like_text = _extract_metric(description, ("Likes", "Like"))
    comment_text = _extract_metric(description, ("Comments", "Comment"))
    media_type = _extract_media_type(soup, post_url)
    media_urls = _extract_media_urls(soup)

    return Post(
        shortcode=shortcode,
        caption=caption,
        timestamp=timestamp,
        like_text=like_text,
        comment_text=comment_text,
        post_url=post_url,
        media_type=media_type,
        media_urls=media_urls,
    )


def _extract_bio(header, username: str) -> str:
    text_nodes = [_clean_text(node.get_text(" ", strip=True)) for node in header.select("section, div, span")]
    filtered = [
        value
        for value in text_nodes
        if value
        and value != username
        and "posts" not in value.lower()
        and "followers" not in value.lower()
        and "following" not in value.lower()
        and "follow" not in value.lower()
    ]
    return filtered[1] if len(filtered) > 1 else ""


def _extract_counts(header, description: str) -> tuple[str, str, str]:
    texts = [_clean_text(item.get_text(" ", strip=True)) for item in header.select("li, section, div, span")]
    post_text = next((text for text in texts if "posts" in text.lower()), "")
    follower_text = next((text for text in texts if "followers" in text.lower()), "")
    following_text = next((text for text in texts if "following" in text.lower()), "")
    if not (post_text and follower_text and following_text) and description:
        pieces = [piece.strip() for piece in description.split(",")]
        if len(pieces) >= 3:
            post_text = post_text or pieces[0]
            follower_text = follower_text or pieces[1]
            following_text = following_text or pieces[2]
    return post_text, follower_text, following_text


def _extract_caption(soup: BeautifulSoup, description: str, title: str) -> str:
    caption = ""
    caption_meta = _meta_property(soup, "og:description")
    for candidate in (caption_meta, description, title):
        if candidate:
            caption = candidate
            break
    caption = re.sub(r"^\d[\d,\.]*\s+Likes?,\s*\d[\d,\.]*\s+Comments?\s*-\s*", "", caption).strip()
    quote_match = re.search(r'on Instagram:\s*["“](.*?)["”]\s*$', caption)
    if quote_match:
        caption = quote_match.group(1)
    else:
        caption = caption.replace(" on Instagram:", "").strip()
    return caption.strip("\" ")


def _extract_timestamp(soup: BeautifulSoup) -> str:
    time_tag = soup.select_one("time[datetime]")
    if time_tag and time_tag.has_attr("datetime"):
        return str(time_tag["datetime"])
    return ""


def _extract_metric(description: str, labels: tuple[str, ...]) -> str:
    for label in labels:
        match = re.search(rf"([\d,\.]+)\s+{label}", description or "", re.IGNORECASE)
        if match:
            return f"{match.group(1)} {label}"
    return ""


def _extract_media_type(soup: BeautifulSoup, post_url: str) -> str:
    og_type = _meta_property(soup, "og:type")
    if "/reel/" in post_url:
        return "REEL"
    if "video" in og_type.lower():
        return "VIDEO"
    if soup.select_one("video"):
        return "VIDEO"
    if soup.select_one("button[aria-label='Next']"):
        return "CAROUSEL"
    return "IMAGE"


def _extract_media_urls(soup: BeautifulSoup) -> list[str]:
    urls: list[str] = []

    og_image = _meta_property(soup, "og:image")
    if og_image:
        urls.append(og_image)

    og_video = _meta_property(soup, "og:video")
    if og_video:
        urls.append(og_video)

    for selector, attribute in (
        ("article img", "src"),
        ("article video", "poster"),
        ("article video", "src"),
        ("main img", "src"),
        ("main video", "poster"),
        ("main video", "src"),
        ("video", "poster"),
        ("video", "src"),
    ):
        for node in soup.select(selector):
            value = str(node.get(attribute) or "").strip()
            if value:
                urls.append(value)

    return _dedupe_preserve_order(urls)


def _extract_post_media_urls(page, post_url: str, media_type: str) -> list[str]:
    if media_type == "CAROUSEL":
        carousel_urls = _extract_carousel_media_urls(page, post_url)
        if carousel_urls:
            return carousel_urls
    active_media_url = _extract_active_media_url(page)
    return [active_media_url] if active_media_url else []


def _extract_carousel_media_urls(page, post_url: str, max_slides: int = 10) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    base_post_url = _normalize_post_url(post_url)

    first_media_url = _extract_active_media_url(page)
    if first_media_url:
        seen.add(first_media_url)
        urls.append(first_media_url)

    for img_index in range(2, max_slides + 1):
        page.goto(f"{base_post_url}?img_index={img_index}", wait_until="domcontentloaded")
        page.wait_for_timeout(600)
        active_media_url = _extract_active_media_url(page)
        if not active_media_url or active_media_url in seen:
            break
        seen.add(active_media_url)
        urls.append(active_media_url)

    return urls


def _extract_active_media_url(page) -> str:
    result = page.evaluate(
        """
        () => {
          const root = document.querySelector('article') || document.querySelector('main');
          if (!root) return '';

          const candidates = Array.from(root.querySelectorAll('img, video'))
            .map(node => {
              const rect = node.getBoundingClientRect();
              const tag = node.tagName.toLowerCase();
              const alt = (node.getAttribute('alt') || '').toLowerCase();
              const url = tag === 'video'
                ? (node.currentSrc || node.getAttribute('src') || node.getAttribute('poster') || '')
                : (node.currentSrc || node.getAttribute('src') || '');
              return {
                url,
                alt,
                area: Math.round((rect.width || 0) * (rect.height || 0)),
                width: Math.round(rect.width || 0),
                height: Math.round(rect.height || 0),
              };
            })
            .filter(item => item.url && item.area > 40000 && !item.alt.includes('profile picture'))
            .sort((a, b) => b.area - a.area);

          return candidates.length ? candidates[0].url : '';
        }
        """
    )
    return str(result or "").strip()


def _dedupe_preserve_order(urls: list[str]) -> list[str]:
    unique_urls: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)
    return unique_urls


def _normalize_post_url(post_url: str) -> str:
    parsed = urlparse(post_url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def _extract_shortcode(post_url: str) -> str:
    path_parts = [part for part in urlparse(post_url).path.split("/") if part]
    return path_parts[-1] if path_parts else ""


def _meta_content(soup: BeautifulSoup, name: str) -> str:
    tag = soup.find("meta", attrs={"name": name})
    if tag and tag.get("content"):
        return str(tag["content"])
    return ""


def _meta_property(soup: BeautifulSoup, prop: str) -> str:
    tag = soup.find("meta", attrs={"property": prop})
    if tag and tag.get("content"):
        return str(tag["content"])
    return ""


def _first_text(container, selectors: list[str]) -> str:
    for selector in selectors:
        node = container.select_one(selector)
        if node:
            return node.get_text(" ", strip=True)
    return ""


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _is_login_or_checkpoint(url: str) -> bool:
    lowered = url.lower()
    return any(part in lowered for part in ("/accounts/login", "/challenge/", "/checkpoint/"))


def _profile_not_found(html: str) -> bool:
    return "Sorry, this page isn't available." in html or "The link you followed may be broken" in html


def _has_visible_posts(page) -> bool:
    return page.locator(PROFILE_POST_LINKS).count() > 0


def scrape_feed(
    limit: int,
    session_dir: Path,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[Post]:
    """Scrape posts from the Instagram main feed (home page).

    Args:
        limit: Maximum number of posts to scrape
        session_dir: Path to directory with persisted browser session
        from_date: Minimum post date (inclusive)
        to_date: Maximum post date (inclusive)

    Returns:
        List of scraped Post objects
    """
    with authenticated_context(session_dir) as context:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        if _is_login_or_checkpoint(page.url):
            raise BrowserSessionError("Instagram redirected to login or checkpoint. Session may be expired.")

        return collect_and_process_posts(context, page, limit, from_date, to_date, post_selector=FEED_POST_LINKS)


def scrape_followers(
    username: str,
    limit: int | None,
    session_dir: Path,
) -> tuple[str, list[Follower]]:
    """Scrape all followers for a given Instagram username.

    Args:
        username: Target Instagram username to scrape followers from
        limit: Maximum number of followers to scrape (None for unlimited)
        session_dir: Path to directory with persisted browser session

    Returns:
        Tuple of (follower count text from profile, list of extracted Follower objects)
    """
    with authenticated_context(session_dir) as context:
        page = context.pages[0] if context.pages else context.new_page()
        profile_url = f"https://www.instagram.com/{username.strip().strip('/')}/"
        page.goto(profile_url, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        if _is_login_or_checkpoint(page.url):
            raise BrowserSessionError("Instagram redirected to login or checkpoint while opening the target profile.")

        html = page.content()
        if _profile_not_found(html):
            raise ScrapeError(f"Profile `{username}` was not found.")

        # Parse profile to get follower count and check if private
        profile = parse_profile_html(html, username)
        if profile.is_private:
            raise ScrapeError(f"Profile `{username}` is private. Followers list is not accessible.")

        # Find and click the followers link to open modal
        followers_link = page.locator(PROFILE_FOLLOWERS_LINK).first
        if not followers_link.is_visible():
            raise ScrapeError(f"Could not find followers link on profile `{username}`.")

        followers_link.click()
        page.wait_for_timeout(1500)

        # Check if modal opened
        modal = page.locator(FOLLOWER_MODAL)
        if modal.count() == 0:
            raise ScrapeError("Followers modal did not open.")

        # Collect followers with incremental scrolling
        followers: list[Follower] = []
        seen_usernames: set[str] = set()
        stagnant_rounds = 0
        max_stagnant = 5

        while (limit is None or len(followers) < limit) and stagnant_rounds < max_stagnant:
            # Extract all visible follower items
            new_count_before = len(followers)

            # Try multiple selector patterns for follower items (Instagram DOM changes often)
            items = []
            for selector in [FOLLOWER_ITEM, FOLLOWER_ITEM_ALT, FOLLOWER_ITEM_ALT2]:
                count = page.locator(selector).count()
                if count > 0:
                    items = page.locator(selector).all()
                    break

            # If still no items found, use brute force - get all divs in dialog that have links
            if not items:
                items = page.locator(f"{FOLLOWER_MODAL} div").all()

            for item in items:
                # Find all links in this item (look for username link)
                links = item.locator(FOLLOWER_USERNAME_LINK).all()
                username_link = None
                for link in links:
                    href = link.get_attribute("href")
                    if href and not href.startswith("/"):
                        continue
                    # Skip links that aren't to a profile
                    if href and ("/p/" in href or "/reel/" in href or "/followers/" in href or "/following/" in href):
                        continue
                    username_link = link
                    break

                if not username_link:
                    continue

                extracted_username = username_link.get_attribute("href")
                if not extracted_username:
                    continue

                # Clean up username from href: "/username/" -> "username"
                parts = [p for p in extracted_username.split("/") if p]
                if not parts:
                    continue
                current_username = parts[-1]

                # Skip if already seen
                if current_username in seen_usernames:
                    continue

                # Get profile URL
                profile_url = f"https://www.instagram.com/{current_username}/"

                # Extract display name - collect all span[dir=auto] text
                display_name = ""
                display_candidates = item.locator(FOLLOWER_DISPLAY_NAME).all()
                display_texts = [_clean_text(candidate.text_content()) for candidate in display_candidates if candidate.text_content()]
                # Filter out empty and the username itself (first one is usually username, second is display name)
                filtered = [t for t in display_texts if t and t != current_username]
                if filtered:
                    display_name = " ".join(filtered)
                elif display_texts:
                    display_name = display_texts[0]

                # Create follower entry
                follower = Follower(
                    username=current_username,
                    display_name=display_name,
                    profile_url=profile_url,
                )
                followers.append(follower)
                seen_usernames.add(current_username)

                # Stop if we hit the limit
                if limit is not None and len(followers) >= limit:
                    break

            # Check if any new followers were added
            if len(followers) == new_count_before:
                stagnant_rounds += 1
            else:
                stagnant_rounds = 0

            # If we've hit the limit, stop
            if limit is not None and len(followers) >= limit:
                break

            # Move mouse into the modal dialog so wheel events target the scrollable container
            modal_box = page.locator(FOLLOWER_MODAL).first
            if modal_box.is_visible():
                # Click to focus the modal
                modal_box.click(position={"x": 100, "y": 200})
                page.wait_for_timeout(200)

            # Just use mouse wheel scrolling - when modal is open, this naturally triggers Instagram's lazy load
            # Scroll multiple times to push for more content
            for _ in range(3):
                page.mouse.wheel(0, 1000)
                page.wait_for_timeout(300)

            # Wait after scrolling for content to load
            page.wait_for_timeout(1000)

        return profile.follower_text, followers[:limit] if limit else followers


def scrape_following(
    username: str,
    limit: int | None,
    session_dir: Path,
) -> tuple[str, list[Follower]]:
    """Scrape all following for a given Instagram username.

    Args:
        username: Target Instagram username to scrape following from
        limit: Maximum number of following to scrape (None for unlimited)
        session_dir: Path to directory with persisted browser session

    Returns:
        Tuple of (following count text from profile, list of extracted Follower objects)
    """
    with authenticated_context(session_dir) as context:
        page = context.pages[0] if context.pages else context.new_page()
        profile_url = f"https://www.instagram.com/{username.strip().strip('/')}/"
        page.goto(profile_url, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        if _is_login_or_checkpoint(page.url):
            raise BrowserSessionError("Instagram redirected to login or checkpoint while opening the target profile.")

        html = page.content()
        if _profile_not_found(html):
            raise ScrapeError(f"Profile `{username}` was not found.")

        # Parse profile to get following count and check if private
        profile = parse_profile_html(html, username)
        if profile.is_private:
            raise ScrapeError(f"Profile `{username}` is private. Following list is not accessible.")

        # Find and click the following link to open modal
        following_link = page.locator(PROFILE_FOLLOWING_LINK).first
        if not following_link.is_visible():
            raise ScrapeError(f"Could not find following link on profile `{username}`.")

        following_link.click()
        page.wait_for_timeout(1500)

        # Check if modal opened
        modal = page.locator(FOLLOWER_MODAL)
        if modal.count() == 0:
            raise ScrapeError("Following modal did not open.")

        # Collect following with incremental scrolling
        following: list[Follower] = []
        seen_usernames: set[str] = set()
        stagnant_rounds = 0
        max_stagnant = 5

        while (limit is None or len(following) < limit) and stagnant_rounds < max_stagnant:
            # Extract all visible following items
            new_count_before = len(following)

            # Try multiple selector patterns for following items (Instagram DOM changes often)
            items = []
            for selector in [FOLLOWER_ITEM, FOLLOWER_ITEM_ALT, FOLLOWER_ITEM_ALT2]:
                count = page.locator(selector).count()
                if count > 0:
                    items = page.locator(selector).all()
                    break

            # If still no items found, use brute force - get all divs in dialog that have links
            if not items:
                items = page.locator(f"{FOLLOWER_MODAL} div").all()

            for item in items:
                # Find all links in this item (look for username link)
                links = item.locator(FOLLOWER_USERNAME_LINK).all()
                username_link = None
                for link in links:
                    href = link.get_attribute("href")
                    if href and not href.startswith("/"):
                        continue
                    # Skip links that aren't to a profile
                    if href and ("/p/" in href or "/reel/" in href or "/followers/" in href or "/following/" in href):
                        continue
                    username_link = link
                    break

                if not username_link:
                    continue

                extracted_username = username_link.get_attribute("href")
                if not extracted_username:
                    continue

                # Clean up username from href: "/username/" -> "username"
                parts = [p for p in extracted_username.split("/") if p]
                if not parts:
                    continue
                current_username = parts[-1]

                # Skip if already seen
                if current_username in seen_usernames:
                    continue

                # Get profile URL
                profile_url = f"https://www.instagram.com/{current_username}/"

                # Extract display name - collect all span text
                display_name = ""
                display_candidates = item.locator(FOLLOWER_DISPLAY_NAME).all()
                display_texts = [_clean_text(candidate.text_content()) for candidate in display_candidates if candidate.text_content()]
                # Filter out empty and the username itself (first one is usually username, second is display name)
                filtered = [t for t in display_texts if t and t != current_username]
                if filtered:
                    display_name = " ".join(filtered)
                elif display_texts:
                    display_name = display_texts[0]

                # Create following entry
                follower = Follower(
                    username=current_username,
                    display_name=display_name,
                    profile_url=profile_url,
                )
                following.append(follower)
                seen_usernames.add(current_username)

                # Stop if we hit the limit
                if limit is not None and len(following) >= limit:
                    break

            # Check if any new following were added
            if len(following) == new_count_before:
                stagnant_rounds += 1
            else:
                stagnant_rounds = 0

            # If we've hit the limit, stop
            if limit is not None and len(following) >= limit:
                break

            # Move mouse into the modal dialog so wheel events target the scrollable container
            modal_box = page.locator(FOLLOWER_MODAL).first
            if modal_box.is_visible():
                # Click to focus the modal
                modal_box.click(position={"x": 100, "y": 200})
                page.wait_for_timeout(200)

            # Just use mouse wheel scrolling - when modal is open, this naturally triggers Instagram's lazy load
            # Scroll multiple times to push for more content
            for _ in range(3):
                page.mouse.wheel(0, 1000)
                page.wait_for_timeout(300)

            # Wait after scrolling for content to load
            page.wait_for_timeout(1000)

        return profile.following_text, following[:limit] if limit else following
