"""
Unified CLI for the social media scraper.
Commands: login-xiaohongshu, login-instagram, login-linkedin, scrape
"""
import asyncio
import click
import os
import json
from typing import Optional
from dotenv import set_key
from pathlib import Path
from loguru import logger
from playwright.async_api import async_playwright

from .models import Account, ScrapeConfig, PlatformResult, AccountMetadata
from .config import load_config
from .output import load_accounts_from_csv, ensure_account_dir, save_platform_output, save_metadata, _clean_filename
from datetime import datetime


def get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent.parent


@click.group()
def main():
    """Unified Social Media Scraper - Scrape Xiaohongshu, Instagram, LinkedIn from a single account list."""
    pass


@main.command()
def login_xiaohongshu():
    """Interactive login for Xiaohongshu, saves cookies to .env."""
    from social_media_scraper.xiaohongshu.interactive_login import InteractiveXHSLogin

    # Change to project root so .env is written correctly
    import os
    os.chdir(get_project_root())

    click.echo("Opening browser for Xiaohongshu login...")
    click.echo("Please scan QR code to login, then follow the prompts.")

    login_helper = InteractiveXHSLogin()
    cookies_str = asyncio.run(login_helper.interactive_login())
    if not cookies_str:
        click.echo("Failed to get cookies, please try again.")
        return

    click.echo("✓ Xiaohongshu cookies saved to .env")


@main.command()
@click.option("--session-dir", default=None, help="Instagram session directory")
def login_instagram(session_dir):
    """Interactive login for Instagram, saves persistent browser session."""
    from social_media_scraper.instagram.browser import login_instagram

    project_root = get_project_root()
    config = load_config(str(project_root))

    if session_dir is None:
        session_dir = config.instagram.session_dir

    click.echo("Opening browser for Instagram login...")
    click.echo("Please login manually in the browser, the browser will close automatically when done.")

    login_instagram(Path(session_dir))
    click.echo(f"✓ Instagram session saved to {session_dir}")


@main.command()
@click.option("--session-file", default=None, help="LinkedIn session file path")
def login_linkedin(session_file):
    """Interactive login for LinkedIn, saves session cookies."""
    project_root = get_project_root()
    config = load_config(str(project_root))

    if session_file is None:
        session_file = config.linkedin.session_file

    click.echo("Opening browser for LinkedIn login...")
    click.echo("Please login manually, then press Enter here when done.")

    asyncio.run(_login_linkedin(session_file))
    click.echo(f"✓ LinkedIn session saved to {session_file}")


async def _login_linkedin(session_file: str):
    import json
    session_path = Path(session_file)
    session_path.parent.mkdir(parents=True, exist_ok=True)

    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=False, slow_mo=50)
    storage_state = None
    if session_path.exists():
        with open(session_path, "r") as f:
            storage_state = json.load(f)

    context = await browser.new_context(storage_state=storage_state)
    page = await context.new_page()
    await page.goto("https://www.linkedin.com/")
    click.echo("Press Enter after you have logged in...")
    input()
    storage_state = await context.storage_state()
    with open(session_path, "w") as f:
        json.dump(storage_state, f, indent=2)
    await browser.close()
    await p.stop()


@main.command()
@click.option("--output", default="existing_connections/linkedin", help="Output directory for JSON results (default: existing_connections/linkedin)")
@click.option("--new-leads-dir", default="new_leads", help="Directory to save new connections (default: new_leads)")
@click.option("--session-file", default=None, help="LinkedIn session file path")
@click.option("--scrape-profiles", is_flag=True, default=False, help="Also scrape full profiles for each connection")
@click.option("--max-scrolls", default=500, help="Maximum number of scroll attempts to load connections")
@click.option("--max-connections", default=100, type=int, help="Maximum number of connections to scrape (default: 100)")
@click.option("--existing-connections", default=None, help="Path to existing connections JSON file for comparison (looks in existing_connections/linkedin/ by default)")
def scrape_linkedin_connections(output, new_leads_dir, session_file, scrape_profiles, max_scrolls, max_connections, existing_connections):
    """Scrape LinkedIn connections, compare with existing, and save new connections to new_leads/."""
    project_root = get_project_root()
    config = load_config(str(project_root))

    if session_file is None:
        session_file = config.linkedin.session_file

    # If existing_connections is not provided, check for the latest file in output directory
    if existing_connections is None:
        output_path = Path(output)
        if output_path.exists():
            # Look for the most recent linkedin_connections.json
            latest_file = output_path / "linkedin_connections.json"
            if latest_file.exists():
                existing_connections = str(latest_file)

    click.echo(f"Scraping LinkedIn connections...")
    click.echo(f"Output directory: {output}")
    click.echo(f"New leads directory: {new_leads_dir}")
    if max_connections:
        click.echo(f"Max connections to scrape: {max_connections}")
    else:
        click.echo("Will scrape all connections")
    if scrape_profiles:
        click.echo("Will also scrape full profiles for each connection (this may take a while)")
    if existing_connections:
        click.echo(f"Will compare with existing connections at: {existing_connections}")
    else:
        click.echo("No existing connections found - will save all as new leads")

    asyncio.run(_scrape_linkedin_connections(
        output_dir=output,
        new_leads_dir=new_leads_dir,
        session_file=session_file,
        scrape_profiles=scrape_profiles,
        max_scrolls=max_scrolls,
        max_connections=max_connections,
        existing_connections_path=existing_connections,
        config=config
    ))


async def _scrape_linkedin_connections(
    output_dir: str,
    new_leads_dir: str,
    session_file: str,
    scrape_profiles: bool,
    max_scrolls: int,
    max_connections: Optional[int],
    existing_connections_path: Optional[str],
    config,
):
    """Scrape LinkedIn connections, compare with existing, and save new connections to new_leads/."""
    from social_media_scraper.linkedin.scraper import LinkedInScraper
    from social_media_scraper.linkedin.utils import (
        load_connections_from_file,
        find_new_connections,
        save_new_connections,
    )
    from datetime import datetime

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    new_leads_path = Path(new_leads_dir)
    new_leads_path.mkdir(parents=True, exist_ok=True)

    # Initialize LinkedIn scraper
    linkedin_scraper = LinkedInScraper(
        session_file=session_file,
        headless=config.browser.headless
    )

    try:
        # Step 1: FIRST load existing connections (before overwriting!)
        existing_conns = []
        if existing_connections_path:
            existing_path = Path(existing_connections_path)
            if existing_path.exists():
                logger.info(f"Loading existing connections from {existing_connections_path}")
                existing_conns = load_connections_from_file(existing_path)

        # Step 2: Scrape connections list
        if max_connections:
            logger.info(f"Scraping connections list (max {max_connections})...")
        else:
            logger.info("Scraping all connections...")
        connections = await linkedin_scraper.scrape_connections(
            max_scrolls=max_scrolls,
            max_connections=max_connections
        )

        if not connections:
            logger.warning("No connections found")
            return

        scraped_at = datetime.now()

        # Step 3: Compare with existing connections and save new connections to new_leads/
        new_connections = connections
        new_connections_objects = []
        from social_media_scraper.linkedin.models import Connection

        # Convert dict connections to Connection objects for comparison
        all_new_conns_objects = []
        for conn_dict in connections:
            try:
                conn = Connection(
                    profile_url=conn_dict["profile_url"],
                    profile_username=conn_dict.get("profile_username")
                )
                all_new_conns_objects.append(conn)
            except Exception as e:
                logger.warning(f"Could not convert connection: {e}")
                continue

        if existing_conns:
            # Find new connections
            new_connections_objects = find_new_connections(all_new_conns_objects, existing_conns)

            # Convert back to dicts
            new_connections = []
            for conn in new_connections_objects:
                new_connections.append({
                    "profile_url": conn.profile_url,
                    "profile_username": conn.profile_username
                })
        else:
            # No existing connections, all are new
            logger.info("No existing connections found, all are new")
            new_connections_objects = all_new_conns_objects

        # Save new connections to new_leads/
        if new_connections_objects:
            saved_file = save_new_connections(
                new_connections_objects,
                new_leads_path,
                scraped_at=scraped_at.isoformat()
            )
            logger.info(f"Saved {len(new_connections_objects)} new connections to {saved_file}")

            # Also convert to CSV format
            from .csv_exporter import convert_leads_to_csv as _convert_leads_to_csv
            csv_file = _convert_leads_to_csv(
                leads_file=saved_file,
                existing_csv=None,
                output_csv=None
            )
            if csv_file:
                logger.info(f"Also converted to CSV: {csv_file}")
        else:
            logger.info("No new connections found")

        # Step 4: LAST - save current connections as the new "existing" for next time
        connections_file = output_path / "linkedin_connections.json"
        with open(connections_file, "w", encoding="utf-8") as f:
            json.dump({
                "scraped_at": scraped_at.isoformat(),
                "connections_count": len(connections),
                "connections": connections,
            }, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved {len(connections)} connections to {connections_file}")

        # Step 2: Optionally scrape full profiles
        if scrape_profiles:
            profiles_dir = output_path / "linkedin_profiles"
            profiles_dir.mkdir(parents=True, exist_ok=True)

            logger.info(f"Scraping full profiles for {len(connections)} connections...")
            successful = 0
            failed = 0

            for i, connection in enumerate(connections):
                profile_username = connection.get("profile_username")
                profile_url = connection.get("profile_url")
                name = connection.get("name", f"connection_{i+1}")

                if not profile_username and not profile_url:
                    logger.warning(f"No profile identifier for {name}, skipping")
                    failed += 1
                    continue

                identifier = profile_username or profile_url
                logger.info(f"[{i+1}/{len(connections)}] Scraping profile for: {name}")

                try:
                    profile_data = await linkedin_scraper.scrape_profile(identifier)

                    # Save individual profile
                    clean_name = _clean_filename(name)
                    profile_file = profiles_dir / f"{clean_name}.json"
                    with open(profile_file, "w", encoding="utf-8") as f:
                        json.dump({
                            "scraped_at": datetime.now().isoformat(),
                            "profile": profile_data,
                        }, f, ensure_ascii=False, indent=2)

                    successful += 1
                    logger.info(f"Successfully scraped profile for: {name}")

                except Exception as e:
                    logger.error(f"Failed to scrape profile for {name}: {e}", exc_info=True)
                    failed += 1

            logger.info(f"Profile scraping complete: {successful} successful, {failed} failed")

    finally:
        # Cleanup
        if linkedin_scraper:
            await linkedin_scraper.close()

    logger.info(f"\n==== LinkedIn connections scraping complete ====")
    logger.info(f"Results saved to: {output_dir}")


@main.command()
@click.option("--username", required=True, help="Instagram username to scrape followers from")
@click.option("--output", default="existing_connections/instagram_followers", help="Output directory for JSON results (default: existing_connections/instagram_followers)")
@click.option("--new-leads-dir", default="new_leads", help="Directory to save new followers (default: new_leads)")
@click.option("--session-dir", default=None, help="Instagram session directory")
@click.option("--max-connections", default=None, type=int, help="Maximum number of followers to scrape (default: all)")
@click.option("--existing-followers", default=None, help="Path to existing followers JSON file for comparison (looks in existing_connections/instagram_followers/ by default)")
def scrape_instagram_followers(username, output, new_leads_dir, session_dir, max_connections, existing_followers):
    """Scrape Instagram followers, compare with existing, and save new followers to new_leads/."""
    project_root = get_project_root()
    config = load_config(str(project_root))

    if session_dir is None:
        session_dir = config.instagram.session_dir

    # If existing_followers is not provided, check for the latest file in output directory
    if existing_followers is None:
        output_path = Path(output)
        if output_path.exists():
            latest_file = output_path / "followers.json"
            if latest_file.exists():
                existing_followers = str(latest_file)

    click.echo(f"Scraping Instagram followers for @{username}...")
    click.echo(f"Output directory: {output}")
    click.echo(f"New leads directory: {new_leads_dir}")
    if max_connections:
        click.echo(f"Max followers to scrape: {max_connections}")
    else:
        click.echo("Will scrape all followers")
    if existing_followers:
        click.echo(f"Will compare with existing followers at: {existing_followers}")
    else:
        click.echo("No existing followers found - will save all as new leads")

    _scrape_instagram_followers(
        username=username,
        output_dir=output,
        new_leads_dir=new_leads_dir,
        session_dir=session_dir,
        max_connections=max_connections,
        existing_followers_path=existing_followers,
        config=config
    )


def _scrape_instagram_followers(
    username: str,
    output_dir: str,
    new_leads_dir: str,
    session_dir: str,
    max_connections: Optional[int],
    existing_followers_path: Optional[str],
    config,
):
    """Scrape Instagram followers, compare with existing, and save new followers to new_leads/."""
    from social_media_scraper.instagram.cli import scrape_followers
    from social_media_scraper.instagram.utils import (
        load_users_from_file,
        find_new_users,
        save_new_users,
        InstagramUser,
    )
    from datetime import datetime
    import json

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    new_leads_path = Path(new_leads_dir)
    new_leads_path.mkdir(parents=True, exist_ok=True)

    # Step 1: FIRST load existing followers (before overwriting!)
    existing_users = []
    if existing_followers_path:
        existing_path = Path(existing_followers_path)
        if existing_path.exists():
            logger.info(f"Loading existing followers from {existing_followers_path}")
            existing_users = load_users_from_file(existing_path)

    # Step 2: Scrape followers list
    if max_connections:
        logger.info(f"Scraping followers (max {max_connections})...")
    else:
        logger.info("Scraping all followers...")

    # Use the Instagram scraper's scrape_followers function
    from social_media_scraper.instagram.scraper import scrape_followers
    follower_count_text, followers_data = scrape_followers(
        username=username,
        limit=max_connections,
        session_dir=Path(session_dir),
    )

    if not followers_data:
        logger.warning("No followers found")
        return

    # Convert to InstagramUser objects
    all_new_users = []
    for follower in followers_data:
        user = InstagramUser(
            username=follower.username,
            profile_url=follower.profile_url
        )
        all_new_users.append(user)

    scraped_at = datetime.now()

    # Step 3: Save current followers as the new "existing" for next time
    followers_file = output_path / "followers.json"
    with open(followers_file, "w", encoding="utf-8") as f:
        json.dump({
            "scraped_at": scraped_at.isoformat(),
            "target_username": username,
            "followers_count_text": follower_count_text,
            "scraped_count": len(all_new_users),
            "followers": [u.to_dict() for u in all_new_users],
        }, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved {len(all_new_users)} followers to {followers_file}")

    # Step 4: Compare with existing followers and save new followers to new_leads/
    new_users = all_new_users
    new_users_objects = []

    if existing_users:
        # Find new followers
        new_users_objects = find_new_users(all_new_users, existing_users)
    else:
        # No existing followers, all are new
        logger.info("No existing followers found, all are new")
        new_users_objects = all_new_users

    # Save new followers to new_leads/
    if new_users_objects:
        saved_file = save_new_users(
            new_users_objects,
            new_leads_path,
            scraped_at=scraped_at.isoformat(),
            user_type="followers"
        )
        logger.info(f"Saved {len(new_users_objects)} new followers to {saved_file}")

        # Also convert to CSV format
        from .csv_exporter import convert_leads_to_csv as _convert_leads_to_csv
        csv_file = _convert_leads_to_csv(
            leads_file=saved_file,
            existing_csv=None,
            output_csv=None
        )
        if csv_file:
            logger.info(f"Also converted to CSV: {csv_file}")
    else:
        logger.info("No new followers found")

    logger.info(f"\n==== Instagram followers scraping complete ====")
    logger.info(f"Results saved to: {output_dir}")


@main.command()
@click.option("--username", required=True, help="Instagram username to scrape following from")
@click.option("--output", default="existing_connections/instagram_following", help="Output directory for JSON results (default: existing_connections/instagram_following)")
@click.option("--new-leads-dir", default="new_leads", help="Directory to save new following (default: new_leads)")
@click.option("--session-dir", default=None, help="Instagram session directory")
@click.option("--max-connections", default=None, type=int, help="Maximum number of following to scrape (default: all)")
@click.option("--existing-following", default=None, help="Path to existing following JSON file for comparison (looks in existing_connections/instagram_following/ by default)")
def scrape_instagram_following(username, output, new_leads_dir, session_dir, max_connections, existing_following):
    """Scrape Instagram following, compare with existing, and save new following to new_leads/."""
    project_root = get_project_root()
    config = load_config(str(project_root))

    if session_dir is None:
        session_dir = config.instagram.session_dir

    # If existing_following is not provided, check for the latest file in output directory
    if existing_following is None:
        output_path = Path(output)
        if output_path.exists():
            latest_file = output_path / "following.json"
            if latest_file.exists():
                existing_following = str(latest_file)

    click.echo(f"Scraping Instagram following for @{username}...")
    click.echo(f"Output directory: {output}")
    click.echo(f"New leads directory: {new_leads_dir}")
    if max_connections:
        click.echo(f"Max following to scrape: {max_connections}")
    else:
        click.echo("Will scrape all following")
    if existing_following:
        click.echo(f"Will compare with existing following at: {existing_following}")
    else:
        click.echo("No existing following found - will save all as new leads")

    _scrape_instagram_following(
        username=username,
        output_dir=output,
        new_leads_dir=new_leads_dir,
        session_dir=session_dir,
        max_connections=max_connections,
        existing_following_path=existing_following,
        config=config
    )


def _scrape_instagram_following(
    username: str,
    output_dir: str,
    new_leads_dir: str,
    session_dir: str,
    max_connections: Optional[int],
    existing_following_path: Optional[str],
    config,
):
    """Scrape Instagram following, compare with existing, and save new following to new_leads/."""
    from social_media_scraper.instagram.scraper import scrape_following
    from social_media_scraper.instagram.utils import (
        load_users_from_file,
        find_new_users,
        save_new_users,
        InstagramUser,
    )
    from datetime import datetime
    import json

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    new_leads_path = Path(new_leads_dir)
    new_leads_path.mkdir(parents=True, exist_ok=True)

    # Step 1: FIRST load existing following (before overwriting!)
    existing_users = []
    if existing_following_path:
        existing_path = Path(existing_following_path)
        if existing_path.exists():
            logger.info(f"Loading existing following from {existing_following_path}")
            existing_users = load_users_from_file(existing_path)

    # Step 2: Scrape following list
    if max_connections:
        logger.info(f"Scraping following (max {max_connections})...")
    else:
        logger.info("Scraping all following...")

    # Use the scrape_following function
    following_count_text, following_data = scrape_following(
        username=username,
        limit=max_connections,
        session_dir=Path(session_dir),
    )

    if not following_data:
        logger.warning("No following found")
        return

    # Convert to InstagramUser objects
    all_new_users = []
    for following in following_data:
        user = InstagramUser(
            username=following.username,
            profile_url=following.profile_url
        )
        all_new_users.append(user)

    scraped_at = datetime.now()

    # Step 3: Save current following as the new "existing" for next time
    following_file = output_path / "following.json"
    with open(following_file, "w", encoding="utf-8") as f:
        json.dump({
            "scraped_at": scraped_at.isoformat(),
            "target_username": username,
            "following_count_text": following_count_text,
            "scraped_count": len(all_new_users),
            "following": [u.to_dict() for u in all_new_users],
        }, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved {len(all_new_users)} following to {following_file}")

    # Step 4: Compare with existing following and save new following to new_leads/
    new_users = all_new_users
    new_users_objects = []

    if existing_users:
        # Find new following
        new_users_objects = find_new_users(all_new_users, existing_users)
    else:
        # No existing following, all are new
        logger.info("No existing following found, all are new")
        new_users_objects = all_new_users

    # Save new following to new_leads/
    if new_users_objects:
        saved_file = save_new_users(
            new_users_objects,
            new_leads_path,
            scraped_at=scraped_at.isoformat(),
            user_type="following"
        )
        logger.info(f"Saved {len(new_users_objects)} new following to {saved_file}")

        # Also convert to CSV format
        from .csv_exporter import convert_leads_to_csv as _convert_leads_to_csv
        csv_file = _convert_leads_to_csv(
            leads_file=saved_file,
            existing_csv=None,
            output_csv=None
        )
        if csv_file:
            logger.info(f"Also converted to CSV: {csv_file}")
    else:
        logger.info("No new following found")

    logger.info(f"\n==== Instagram following scraping complete ====")
    logger.info(f"Results saved to: {output_dir}")


@main.command()
@click.option("--accounts", required=True, help="CSV file with account list")
@click.option("--output", required=True, help="Output directory for JSON results")
@click.option("--from-date", default=None, help="Start date (YYYY-MM-DD) for XHS/Instagram")
@click.option("--to-date", default=None, help="End date (YYYY-MM-DD) for XHS/Instagram")
@click.option("--download-media", is_flag=True, default=False, help="Download media files (images/videos)")
def scrape(accounts, output, from_date, to_date, download_media):
    """Scrape all accounts from the account list."""
    project_root = get_project_root()
    config = load_config(str(project_root))

    # Validate date format
    if from_date:
        try:
            datetime.strptime(from_date, "%Y-%m-%d")
        except ValueError:
            logger.error("Invalid from-date format, should be YYYY-MM-DD")
            return
    if to_date:
        try:
            datetime.strptime(to_date, "%Y-%m-%d")
        except ValueError:
            logger.error("Invalid to-date format, should be YYYY-MM-DD")
            return

    # Load accounts
    accounts = load_accounts_from_csv(accounts)
    if not accounts:
        logger.error("No accounts loaded from file")
        return

    logger.info(f"Starting scrape with {len(accounts)} accounts, from_date={from_date}, to_date={to_date}")

    asyncio.run(_scrape_all(
        accounts=accounts,
        output_dir=output,
        from_date=from_date,
        to_date=to_date,
        download_media=download_media,
        config=config
    ))


async def _scrape_all(
    accounts: list[Account],
    output_dir: str,
    from_date: str,
    to_date: str,
    download_media: bool,
    config,
):
    """Scrape all accounts sequentially."""

    # Initialize scrapers as needed
    xhs_scraper = None
    if config.xiaohongshu.cookies:
        from social_media_scraper.xiaohongshu.scraper import XiaohongshuScraper
        xhs_scraper = XiaohongshuScraper(
            cookies=config.xiaohongshu.cookies,
            js_path=config.xiaohongshu.js_path
        )
    else:
        logger.warning("No Xiaohongshu cookies found - skipping XHS scraping. Run login-xiaohongshu first.")

    # LinkedIn
    linkedin_scraper = None
    from social_media_scraper.linkedin.scraper import LinkedInScraper
    linkedin_scraper = LinkedInScraper(
        session_file=config.linkedin.session_file,
        headless=config.browser.headless
    )

    # Instagram
    from social_media_scraper.instagram.scraper import scrape_profile, ScrapeError
    from social_media_scraper.instagram.storage import download_post_media

    successful = 0
    failed = 0

    for account in accounts:
        logger.info(f"\n==== Processing account: {account.name} ====")
        scraped_at = datetime.now()
        platform_results = {}
        platforms_scraped = []

        # Instagram
        if account.instagram:
            try:
                logger.info(f"Scraping Instagram @{account.instagram}")
                from_date_obj = None
                to_date_obj = None
                if from_date:
                    from_date_obj = datetime.strptime(from_date, "%Y-%m-%d").date()
                if to_date:
                    to_date_obj = datetime.strptime(to_date, "%Y-%m-%d").date()

                # Instagram uses sync playwright, run in thread to avoid sync-in-async error
                import functools
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor() as executor:
                    profile, posts = await asyncio.get_event_loop().run_in_executor(
                        executor,
                        functools.partial(
                            scrape_profile,
                            username=account.instagram,
                            limit=1000,  # Large limit to get all posts
                            session_dir=Path(config.instagram.session_dir),
                            from_date=from_date_obj,
                            to_date=to_date_obj,
                            headless=config.browser.headless,
                        )
                    )

                # Convert posts to dict for JSON output
                posts_data = []
                for post in posts:
                    # Parse like count from like_text
                    likes = None
                    if post.like_text:
                        import re
                        match = re.search(r'(\d+(?:,\d+)*)', post.like_text.replace(',', ''))
                        if match:
                            likes = int(match.group(1))

                    posts_data.append({
                        "post_url": post.post_url,
                        "shortcode": post.shortcode,
                        "timestamp": post.timestamp,
                        "like_text": post.like_text,
                        "likes_count": likes,
                        "caption": post.caption,
                        "comment_text": post.comment_text,
                        "media_type": post.media_type,
                        "media_urls": post.media_urls,
                        "is_video": post.media_type == "video",
                    })

                result = PlatformResult(
                    platform="instagram",
                    account_handle=account.instagram,
                    scraped_at=scraped_at,
                    items_count=len(posts_data),
                    data=posts_data,
                    success=True,
                )
                platform_results["instagram"] = result
                platforms_scraped.append("instagram")

                # Save output
                account_dir = ensure_account_dir(output_dir, account.name)
                save_platform_output(account_dir, result)

                if download_media:
                    from social_media_scraper.output import _clean_filename
                    media_dir = get_project_root() / "media" / _clean_filename(account.name) / "instagram"
                    media_dir.mkdir(parents=True, exist_ok=True)
                    with ThreadPoolExecutor() as executor:
                        downloaded = await asyncio.get_event_loop().run_in_executor(
                            executor,
                            functools.partial(download_post_media, posts, media_dir)
                        )
                    logger.info(f"Downloaded {downloaded} media files to {media_dir}")

                logger.info(f"Instagram: scraped {len(posts_data)} posts")
            except Exception as e:
                logger.error(f"Failed to scrape Instagram for {account.name}: {e}", exc_info=True)
                platform_results["instagram"] = PlatformResult(
                    platform="instagram",
                    account_handle=account.instagram,
                    scraped_at=scraped_at,
                    items_count=0,
                    data=[],
                    success=False,
                    error=str(e),
                )

        # Xiaohongshu
        if account.xiaohongshu and xhs_scraper:
            try:
                logger.info(f"Scraping Xiaohongshu {account.xiaohongshu}")
                result_data = xhs_scraper.scrape_user(
                    account.xiaohongshu,
                    from_date=from_date,
                    to_date=to_date,
                    download_media=download_media,
                    media_dir=str(get_project_root() / "media" / _clean_filename(account.name) / "xiaohongshu") if download_media else None
                )

                notes = result_data["notes"]
                result = PlatformResult(
                    platform="xiaohongshu",
                    account_handle=account.xiaohongshu,
                    scraped_at=scraped_at,
                    items_count=len(notes),
                    data=notes,
                    success=True,
                )
                platform_results["xiaohongshu"] = result
                platforms_scraped.append("xiaohongshu")

                account_dir = ensure_account_dir(output_dir, account.name)
                save_platform_output(account_dir, result)
                logger.info(f"Xiaohongshu: scraped {len(notes)} notes")
            except Exception as e:
                logger.error(f"Failed to scrape Xiaohongshu for {account.name}: {e}", exc_info=True)
                platform_results["xiaohongshu"] = PlatformResult(
                    platform="xiaohongshu",
                    account_handle=account.xiaohongshu,
                    scraped_at=scraped_at,
                    items_count=0,
                    data=[],
                    success=False,
                    error=str(e),
                )

        # LinkedIn
        if account.linkedin:
            try:
                logger.info(f"Scraping LinkedIn profile {account.linkedin}")
                result_data = await linkedin_scraper.scrape_profile(account.linkedin)

                result = PlatformResult(
                    platform="linkedin",
                    account_handle=account.linkedin,
                    scraped_at=scraped_at,
                    items_count=1,
                    data=result_data,
                    success=True,
                )
                platform_results["linkedin"] = result
                platforms_scraped.append("linkedin")

                account_dir = ensure_account_dir(output_dir, account.name)
                save_platform_output(account_dir, result)
                logger.info(f"LinkedIn: scraped profile {result_data.get('name', 'unknown')}")
            except Exception as e:
                logger.error(f"Failed to scrape LinkedIn for {account.name}: {e}", exc_info=True)
                platform_results["linkedin"] = PlatformResult(
                    platform="linkedin",
                    account_handle=account.linkedin,
                    scraped_at=scraped_at,
                    items_count=0,
                    data={},
                    success=False,
                    error=str(e),
                )

        # Save metadata
        metadata = AccountMetadata(
            account_name=account.name,
            scraped_at=scraped_at,
            from_date=from_date,
            to_date=to_date,
            platforms_scraped=platforms_scraped,
            platform_results=platform_results,
        )
        save_metadata(output_dir, account, metadata)

        if len(platforms_scraped) > 0:
            successful += 1
        else:
            failed += 1

    # Cleanup
    if linkedin_scraper:
        await linkedin_scraper.close()

    logger.info(f"\n==== Scraping complete ====")
    logger.info(f"Successful accounts: {successful}, Failed: {failed}")
    logger.info(f"Results saved to: {output_dir}")


@main.command()
@click.option("--input", required=True, help="Input data directory (usually data/)")
@click.option("--output", required=True, help="Output directory for LLM outputs (usually LLM_outputs/)")
@click.option("--from-date", default=None, help="Filter content after this date (YYYY-MM-DD)")
@click.option("--to-date", default=None, help="Filter content before this date (YYYY-MM-DD)")
@click.option("--account", default=None, help="Only process specific account (for testing)")
@click.option("--no-json", is_flag=True, default=False, help="Don't save JSON output, only markdown")
def generate_llm_outputs(input, output, from_date, to_date, account, no_json):
    """Generate insurance lead analysis from already scraped data using 3-agent Doubao LLM pipeline."""
    from social_media_scraper.llm_analyzer.reader import ContentAggregator
    from social_media_scraper.llm_analyzer.pipeline import ThreeAgentPipeline
    from social_media_scraper.llm_analyzer.processor import LeadProcessor

    project_root = get_project_root()
    config = load_config(str(project_root))

    # Validate date format
    if from_date:
        try:
            datetime.strptime(from_date, "%Y-%m-%d")
        except ValueError:
            logger.error("Invalid from-date format, should be YYYY-MM-DD")
            return
    if to_date:
        try:
            datetime.strptime(to_date, "%Y-%m-%d")
        except ValueError:
            logger.error("Invalid to-date format, should be YYYY-MM-DD")
            return

    # Check Doubao config
    if not config.doubao:
        logger.error("Doubao not configured. Please set DOUBAO_API_KEY and DOUBAO_ENDPOINT in .env")
        return

    # Initialize components
    aggregator = ContentAggregator(input, from_date, to_date)
    pipeline = ThreeAgentPipeline(
        api_key=config.doubao.api_key,
        endpoint=config.doubao.endpoint,
        model=config.doubao.model,
    )
    processor = LeadProcessor(output)

    # Get accounts
    if account:
        accounts = [account]
    else:
        accounts = aggregator.list_accounts()

    if not accounts:
        logger.error(f"No accounts found in input directory: {input}")
        return

    logger.info(f"Starting 3-agent lead generation with {len(accounts)} accounts")
    logger.info(f"Date range: {from_date} to {to_date}")

    successful = 0
    failed = 0

    for acc in accounts:
        logger.info(f"\n==== Processing account: {acc} ====")

        try:
            # Aggregate content
            aggregated = aggregator.aggregate_account(acc)
            if not aggregated or not aggregated.items:
                logger.warning(f"No content found for {acc}, skipping")
                failed += 1
                continue

            # Run 3-agent pipeline
            profile_summary, structured_flags, selling_points = pipeline.run(aggregated)

            # Save output
            processor.process_and_save(
                account_name=acc,
                aggregated=aggregated,
                profile_summary=profile_summary,
                structured_flags=structured_flags,
                selling_points=selling_points,
                from_date=from_date,
                to_date=to_date,
                save_json=not no_json,
            )

            successful += 1
            sp_count = len(selling_points.selling_points) if selling_points else 0
            logger.info(f"Completed {acc}: {sp_count} selling points generated")

        except Exception as e:
            logger.error(f"Failed to process {acc}: {e}", exc_info=True)
            failed += 1

    logger.info(f"\n==== 3-agent lead generation complete ====")
    logger.info(f"Successful accounts: {successful}, Failed: {failed}")
    logger.info(f"Results saved to: {output}")


# Backwards compatibility alias - just call the same function
@main.command(name="generate-leads")
@click.option("--input", required=True, help="Input data directory (usually data/)")
@click.option("--output", required=True, help="Output directory for LLM outputs (usually LLM_outputs/)")
@click.option("--from-date", default=None, help="Filter content after this date (YYYY-MM-DD)")
@click.option("--to-date", default=None, help="Filter content before this date (YYYY-MM-DD)")
@click.option("--account", default=None, help="Only process specific account (for testing)")
@click.option("--no-json", is_flag=True, default=False, help="Don't save JSON output, only markdown")
def generate_leads_alias(input, output, from_date, to_date, account, no_json):
    """Alias for generate-llm-outputs (backwards compatibility)."""
    return generate_llm_outputs.callback(input, output, from_date, to_date, account, no_json)


@main.command()
@click.option("--accounts", required=True, help="CSV file with account list")
@click.option("--from-date", default=None, help="Start date (YYYY-MM-DD) for XHS/Instagram")
@click.option("--to-date", default=None, help="End date (YYYY-MM-DD) for XHS/Instagram")
@click.option("--download-media", is_flag=True, default=False, help="Download images/videos")
@click.option("--no-clean", is_flag=True, default=False, help="Don't clean data/media folders before running")
def pipeline(accounts, from_date, to_date, download_media, no_clean):
    """Run full end-to-end pipeline: clean -> scrape -> generate leads."""
    import shutil

    project_root = get_project_root()

    # Clean up data and media folders unless --no-clean is specified
    if not no_clean:
        logger.info("Cleaning up data/ and media/ folders...")
        for folder_name in ["data", "media"]:
            folder_path = project_root / folder_name
            if folder_path.exists():
                shutil.rmtree(folder_path)
                logger.info(f"  Removed {folder_name}/")
            folder_path.mkdir(exist_ok=True)

    # Step 1: Scrape
    logger.info("\n" + "="*50)
    logger.info("STEP 1: SCRAPING")
    logger.info("="*50)

    # Call scrape function directly
    from social_media_scraper.output import load_accounts_from_csv, ensure_account_dir, save_platform_output, save_metadata, _clean_filename

    # Validate date format
    if from_date:
        try:
            datetime.strptime(from_date, "%Y-%m-%d")
        except ValueError:
            logger.error("Invalid from-date format, should be YYYY-MM-DD")
            return
    if to_date:
        try:
            datetime.strptime(to_date, "%Y-%m-%d")
        except ValueError:
            logger.error("Invalid to-date format, should be YYYY-MM-DD")
            return

    # Load accounts
    account_list = load_accounts_from_csv(accounts)
    if not account_list:
        logger.error("No accounts loaded from file")
        return

    config = load_config(str(project_root))

    logger.info(f"Starting scrape with {len(account_list)} accounts, from_date={from_date}, to_date={to_date}")

    # Run scrape (reuse the same logic as scrape command)
    from social_media_scraper.models import Account, ScrapeConfig, PlatformResult, AccountMetadata

    async def run_scrape():
        from datetime import datetime
        from social_media_scraper.output import _clean_filename
        # Initialize scrapers as needed
        xhs_scraper = None
        if config.xiaohongshu.cookies:
            from social_media_scraper.xiaohongshu.scraper import XiaohongshuScraper
            xhs_scraper = XiaohongshuScraper(
                cookies=config.xiaohongshu.cookies,
                js_path=config.xiaohongshu.js_path
            )
        else:
            logger.warning("No Xiaohongshu cookies found - skipping XHS scraping. Run login-xiaohongshu first.")

        # LinkedIn
        linkedin_scraper = None
        from social_media_scraper.linkedin.scraper import LinkedInScraper
        linkedin_scraper = LinkedInScraper(
            session_file=config.linkedin.session_file,
            headless=config.browser.headless
        )

        # Instagram
        from social_media_scraper.instagram.scraper import scrape_profile, ScrapeError
        from social_media_scraper.instagram.storage import download_post_media

        successful = 0
        failed = 0

        output_dir = "data/"

        for account in account_list:
            logger.info(f"\n==== Processing account: {account.name} ====")
            scraped_at = datetime.now()
            platform_results = {}
            platforms_scraped = []

            # Instagram
            if account.instagram:
                try:
                    logger.info(f"Scraping Instagram @{account.instagram}")
                    from_date_obj = None
                    to_date_obj = None
                    if from_date:
                        from_date_obj = datetime.strptime(from_date, "%Y-%m-%d").date()
                    if to_date:
                        to_date_obj = datetime.strptime(to_date, "%Y-%m-%d").date()

                    # Instagram uses sync playwright, run in thread to avoid sync-in-async error
                    import functools
                    from concurrent.futures import ThreadPoolExecutor
                    with ThreadPoolExecutor() as executor:
                        profile, posts = await asyncio.get_event_loop().run_in_executor(
                            executor,
                            functools.partial(
                                scrape_profile,
                                username=account.instagram,
                                limit=1000,  # Large limit to get all posts
                                session_dir=Path(config.instagram.session_dir),
                                from_date=from_date_obj,
                                to_date=to_date_obj,
                                headless=config.browser.headless,
                            )
                        )

                    # Convert posts to dict for JSON output
                    posts_data = []
                    for post in posts:
                        # Parse like count from like_text
                        likes = None
                        if post.like_text:
                            import re
                            match = re.search(r'(\d+(?:,\d+)*)', post.like_text.replace(',', ''))
                            if match:
                                likes = int(match.group(1))

                        posts_data.append({
                            "post_url": post.post_url,
                            "shortcode": post.shortcode,
                            "timestamp": post.timestamp,
                            "like_text": post.like_text,
                            "likes_count": likes,
                            "caption": post.caption,
                            "comment_text": post.comment_text,
                            "media_type": post.media_type,
                            "media_urls": post.media_urls,
                            "is_video": post.media_type == "video",
                        })

                    result = PlatformResult(
                        platform="instagram",
                        account_handle=account.instagram,
                        scraped_at=scraped_at,
                        items_count=len(posts_data),
                        data=posts_data,
                        success=True,
                    )
                    platform_results["instagram"] = result
                    platforms_scraped.append("instagram")

                    # Save output
                    account_dir = ensure_account_dir(output_dir, account.name)
                    save_platform_output(account_dir, result)

                    if download_media:
                        from social_media_scraper.output import _clean_filename
                        media_dir = project_root / "media" / _clean_filename(account.name) / "instagram"
                        media_dir.mkdir(parents=True, exist_ok=True)
                        with ThreadPoolExecutor() as executor:
                            downloaded = await asyncio.get_event_loop().run_in_executor(
                                executor,
                                functools.partial(download_post_media, posts, media_dir)
                            )
                        logger.info(f"Downloaded {downloaded} media files to {media_dir}")

                    logger.info(f"Instagram: scraped {len(posts_data)} posts")
                except Exception as e:
                    logger.error(f"Failed to scrape Instagram for {account.name}: {e}", exc_info=True)
                    platform_results["instagram"] = PlatformResult(
                        platform="instagram",
                        account_handle=account.instagram,
                        scraped_at=scraped_at,
                        items_count=0,
                        data=[],
                        success=False,
                        error=str(e),
                    )

            # Xiaohongshu
            if account.xiaohongshu and xhs_scraper:
                try:
                    logger.info(f"Scraping Xiaohongshu {account.xiaohongshu}")
                    result_data = xhs_scraper.scrape_user(
                        account.xiaohongshu,
                        from_date=from_date,
                        to_date=to_date,
                        download_media=download_media,
                        media_dir=str(project_root / "media" / _clean_filename(account.name) / "xiaohongshu") if download_media else None
                    )

                    notes = result_data["notes"]
                    result = PlatformResult(
                        platform="xiaohongshu",
                        account_handle=account.xiaohongshu,
                        scraped_at=scraped_at,
                        items_count=len(notes),
                        data=notes,
                        success=True,
                    )
                    platform_results["xiaohongshu"] = result
                    platforms_scraped.append("xiaohongshu")

                    account_dir = ensure_account_dir(output_dir, account.name)
                    save_platform_output(account_dir, result)
                    logger.info(f"Xiaohongshu: scraped {len(notes)} notes")
                except Exception as e:
                    logger.error(f"Failed to scrape Xiaohongshu for {account.name}: {e}", exc_info=True)
                    platform_results["xiaohongshu"] = PlatformResult(
                        platform="xiaohongshu",
                        account_handle=account.xiaohongshu,
                        scraped_at=scraped_at,
                        items_count=0,
                        data=[],
                        success=False,
                        error=str(e),
                    )

            # LinkedIn
            if account.linkedin:
                try:
                    logger.info(f"Scraping LinkedIn profile {account.linkedin}")
                    result_data = await linkedin_scraper.scrape_profile(account.linkedin)

                    result = PlatformResult(
                        platform="linkedin",
                        account_handle=account.linkedin,
                        scraped_at=scraped_at,
                        items_count=1,
                        data=result_data,
                        success=True,
                    )
                    platform_results["linkedin"] = result
                    platforms_scraped.append("linkedin")

                    account_dir = ensure_account_dir(output_dir, account.name)
                    save_platform_output(account_dir, result)
                    logger.info(f"LinkedIn: scraped profile {result_data.get('name', 'unknown')}")
                except Exception as e:
                    logger.error(f"Failed to scrape LinkedIn for {account.name}: {e}", exc_info=True)
                    platform_results["linkedin"] = PlatformResult(
                        platform="linkedin",
                        account_handle=account.linkedin,
                        scraped_at=scraped_at,
                        items_count=0,
                        data={},
                        success=False,
                        error=str(e),
                    )

            # Save metadata
            metadata = AccountMetadata(
                account_name=account.name,
                scraped_at=scraped_at,
                from_date=from_date,
                to_date=to_date,
                platforms_scraped=platforms_scraped,
                platform_results=platform_results,
            )
            save_metadata(output_dir, account, metadata)

            if len(platforms_scraped) > 0:
                successful += 1
            else:
                failed += 1

        # Cleanup
        if linkedin_scraper:
            await linkedin_scraper.close()

        logger.info(f"\n==== Scraping complete ====")
        logger.info(f"Successful accounts: {successful}, Failed: {failed}")
        logger.info(f"Results saved to: {output_dir}")

    asyncio.run(run_scrape())

    # Step 2: Generate leads
    logger.info("\n" + "="*50)
    logger.info("STEP 2: GENERATE LEADS")
    logger.info("="*50)

    # Call generate_leads function directly with 3-agent pipeline
    from social_media_scraper.llm_analyzer.reader import ContentAggregator
    from social_media_scraper.llm_analyzer.pipeline import ThreeAgentPipeline
    from social_media_scraper.llm_analyzer.processor import LeadProcessor

    # Check Doubao config
    if not config.doubao:
        logger.error("Doubao not configured. Please set DOUBAO_API_KEY and DOUBAO_ENDPOINT in .env")
        return

    # Initialize components
    aggregator = ContentAggregator("data/", from_date, to_date)
    pipeline = ThreeAgentPipeline(
        api_key=config.doubao.api_key,
        endpoint=config.doubao.endpoint,
        model=config.doubao.model,
    )
    processor = LeadProcessor("LLM_outputs/")

    # Get accounts
    accounts = aggregator.list_accounts()

    if not accounts:
        logger.error(f"No accounts found in input directory: data/")
        return

    logger.info(f"Starting 3-agent lead generation with {len(accounts)} accounts")
    logger.info(f"Date range: {from_date} to {to_date}")

    successful = 0
    failed = 0

    for acc in accounts:
        logger.info(f"\n==== Processing account: {acc} ====")

        try:
            # Aggregate content
            aggregated = aggregator.aggregate_account(acc)
            if not aggregated or not aggregated.items:
                logger.warning(f"No content found for {acc}, skipping")
                failed += 1
                continue

            # Run 3-agent pipeline
            profile_summary, structured_flags, selling_points = pipeline.run(aggregated)

            # Save output
            processor.process_and_save(
                account_name=acc,
                aggregated=aggregated,
                profile_summary=profile_summary,
                structured_flags=structured_flags,
                selling_points=selling_points,
                from_date=from_date,
                to_date=to_date,
                save_json=True,
            )

            successful += 1
            sp_count = len(selling_points.selling_points) if selling_points else 0
            logger.info(f"Completed {acc}: {sp_count} selling points generated")

        except Exception as e:
            logger.error(f"Failed to process {acc}: {e}", exc_info=True)
            failed += 1

    logger.info(f"\n==== 3-agent lead generation complete ====")
    logger.info(f"Successful accounts: {successful}, Failed: {failed}")
    logger.info(f"Results saved to: LLM_outputs/")

    logger.info("\n" + "="*50)
    logger.info("PIPELINE COMPLETE!")
    logger.info("="*50)


@main.command()
@click.option("--new-leads-dir", default="new_leads", help="Directory containing new leads JSON files (default: new_leads)")
@click.option("--accounts-csv", default="accounts/leads.csv", help="Path to accounts CSV file to update (default: accounts/leads.csv)")
def merge_all_leads_to_accounts(new_leads_dir, accounts_csv):
    """Merge all new leads JSON files into accounts CSV."""
    from .csv_exporter import merge_all_leads_to_accounts_csv as _merge_all_leads

    new_leads_path = Path(new_leads_dir)
    accounts_path = Path(accounts_csv)

    result = _merge_all_leads(
        new_leads_dir=new_leads_path,
        accounts_csv=accounts_path
    )

    if result:
        logger.info(f"\n==== All leads merged to accounts CSV ====")
        logger.info(f"Accounts CSV updated: {result}")
    else:
        logger.warning("No leads were merged")


@main.command()
@click.option("--leads-file", required=True, help="Path to new leads JSON file")
@click.option("--existing-csv", default=None, help="Path to existing accounts CSV to merge with")
@click.option("--output-csv", default=None, help="Path for output CSV (defaults to leads-file with .csv extension)")
def convert_leads_to_csv(leads_file, existing_csv, output_csv):
    """Convert new leads JSON to accounts CSV format."""
    from .csv_exporter import convert_leads_to_csv as _convert_leads_to_csv

    leads_path = Path(leads_file)
    existing_path = Path(existing_csv) if existing_csv else None
    output_path = Path(output_csv) if output_csv else None

    result = _convert_leads_to_csv(
        leads_file=leads_path,
        existing_csv=existing_path,
        output_csv=output_path
    )

    if result:
        logger.info(f"\n==== Leads conversion complete ====")
        logger.info(f"CSV saved to: {result}")
    else:
        logger.warning("No leads were converted")


if __name__ == "__main__":
    main()
