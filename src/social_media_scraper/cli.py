"""
Unified CLI for the social media scraper.
Commands: login-xiaohongshu, login-instagram, login-linkedin, scrape
"""
import asyncio
import click
import os
from dotenv import set_key
from pathlib import Path
from loguru import logger
from playwright.async_api import async_playwright

from .models import Account, ScrapeConfig, PlatformResult, AccountMetadata
from .config import load_config
from .output import load_accounts_from_csv, ensure_account_dir, save_platform_output, save_metadata
from datetime import datetime


def get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent.parent.parent


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
                    media_dir = get_project_root() / "media" / account.name / "instagram"
                    media_dir.mkdir(parents=True, exist_ok=True)
                    with ThreadPoolExecutor() as executor:
                        await asyncio.get_event_loop().run_in_executor(
                            executor,
                            functools.partial(
                                lambda: [download_post_media(post, media_dir) for post in posts]
                            )
                        )
                    logger.info(f"Downloaded {len(posts_data)} media files to {media_dir}")

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
                    media_dir=str(get_project_root() / "media" / account.name / "xiaohongshu") if download_media else None
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


if __name__ == "__main__":
    main()
