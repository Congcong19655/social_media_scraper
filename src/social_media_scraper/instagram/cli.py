from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.error import URLError

from social_media_scraper.instagram.browser import BrowserSessionError, login_instagram
from social_media_scraper.instagram.scraper import ScrapeError, scrape_profile, scrape_followers
from social_media_scraper.instagram.storage import default_output_path, download_post_media, write_scrape_result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Instagram scraping PoC.")
    subparsers = parser.add_subparsers(dest="command")

    login_parser = subparsers.add_parser(
        "login-instagram",
        help="Open a persistent browser for manual Instagram login.",
    )
    login_parser.add_argument(
        "--session-dir",
        default=".session/instagram",
        help="Directory used to persist the browser session.",
    )

    scrape_parser = subparsers.add_parser(
        "scrape-profile",
        help="Scrape visible posts from an Instagram profile.",
    )
    scrape_parser.add_argument("--username", required=True, help="Instagram username to scrape.")
    scrape_parser.add_argument("--limit", type=int, default=12, help="Maximum number of posts to scrape.")
    scrape_parser.add_argument(
        "--output",
        help="Output JSON file path. Defaults to data/<username>.json.",
    )
    scrape_parser.add_argument(
        "--session-dir",
        default=".session/instagram",
        help="Directory used to persist the browser session.",
    )
    scrape_parser.add_argument(
        "--download-media",
        action="store_true",
        help="Download scraped media files into a local directory.",
    )
    scrape_parser.add_argument(
        "--media-dir",
        help="Directory for downloaded media. Defaults to data/<username>_media.",
    )
    scrape_parser.add_argument(
        "--from-date",
        help="Minimum post date (inclusive), format: YYYY-MM-DD.",
    )
    scrape_parser.add_argument(
        "--to-date",
        help="Maximum post date (inclusive), format: YYYY-MM-DD.",
    )

    scrape_followers_parser = subparsers.add_parser(
        "scrape-followers",
        help="Scrape followers list from an Instagram profile.",
    )
    scrape_followers_parser.add_argument("--username", required=True, help="Instagram username to scrape followers from.")
    scrape_followers_parser.add_argument("--limit", type=int, help="Maximum number of followers to scrape (default: unlimited).")
    scrape_followers_parser.add_argument(
        "--output",
        help="Output JSON file path. Defaults to data/<username>_followers.json.",
    )
    scrape_followers_parser.add_argument(
        "--session-dir",
        default=".session/instagram",
        help="Directory used to persist the browser session.",
    )

    scrape_following_parser = subparsers.add_parser(
        "scrape-following",
        help="Scrape following list from an Instagram profile (people you follow).",
    )
    scrape_following_parser.add_argument("--username", required=True, help="Instagram username to scrape following from.")
    scrape_following_parser.add_argument("--limit", type=int, help="Maximum number of accounts to scrape (default: unlimited).")
    scrape_following_parser.add_argument(
        "--output",
        help="Output JSON file path. Defaults to data/<username>_following.json.",
    )
    scrape_following_parser.add_argument(
        "--session-dir",
        default=".session/instagram",
        help="Directory used to persist the browser session.",
    )

    scrape_feed_parser = subparsers.add_parser(
        "scrape-feed",
        help="Scrape posts from your Instagram main feed (home page - latest posts from people you follow).",
    )
    scrape_feed_parser.add_argument("--limit", type=int, default=20, help="Maximum number of posts to scrape.")
    scrape_feed_parser.add_argument(
        "--output",
        help="Output JSON file path. Defaults to data/feed.json.",
    )
    scrape_feed_parser.add_argument(
        "--session-dir",
        default=".session/instagram",
        help="Directory used to persist the browser session.",
    )
    scrape_feed_parser.add_argument(
        "--download-media",
        action="store_true",
        help="Download scraped media files into a local directory.",
    )
    scrape_feed_parser.add_argument(
        "--media-dir",
        help="Directory for downloaded media. Defaults to data/feed_media.",
    )
    scrape_feed_parser.add_argument(
        "--from-date",
        help="Minimum post date (inclusive), format: YYYY-MM-DD.",
    )
    scrape_feed_parser.add_argument(
        "--to-date",
        help="Maximum post date (inclusive), format: YYYY-MM-DD.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "login-instagram":
            login_instagram(Path(args.session_dir))
            print(f"Instagram session saved under {Path(args.session_dir)}")
            return 0

        if args.command == "scrape-profile":
            from datetime import date

            # Parse date filters
            parsed_from_date = None
            if args.from_date:
                try:
                    parsed_from_date = date.fromisoformat(args.from_date)
                except ValueError:
                    print(f"Error: Invalid --from-date format '{args.from_date}', expected YYYY-MM-DD", file=sys.stderr)
                    return 1

            parsed_to_date = None
            if args.to_date:
                try:
                    parsed_to_date = date.fromisoformat(args.to_date)
                except ValueError:
                    print(f"Error: Invalid --to-date format '{args.to_date}', expected YYYY-MM-DD", file=sys.stderr)
                    return 1

            output_path = Path(args.output) if args.output else default_output_path(args.username)
            profile, posts = scrape_profile(
                username=args.username,
                limit=max(args.limit, 1),
                session_dir=Path(args.session_dir),
                from_date=parsed_from_date,
                to_date=parsed_to_date,
            )
            write_scrape_result(output_path, profile, posts)
            downloaded = 0
            if args.download_media:
                media_dir = Path(args.media_dir) if args.media_dir else Path("data") / f"{args.username}_media"
                downloaded = download_post_media(posts, media_dir)
            print(f"Wrote {len(posts)} posts to {output_path}")
            if args.download_media:
                print(f"Downloaded {downloaded} media files")
            return 0

        if args.command == "scrape-followers":
            # Determine output path
            if args.output:
                output_path = Path(args.output)
            else:
                # Default: data/<username>_followers.json
                output_path = Path("data") / f"{args.username}_followers.json"

            # Create parent directory if it doesn't exist
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Run scraping
            follower_count_text, followers = scrape_followers(
                username=args.username,
                limit=args.limit,
                session_dir=Path(args.session_dir),
            )

            # Write output JSON
            import json
            output_data = {
                "target_username": args.username,
                "followers_count_text": follower_count_text,
                "scraped_count": len(followers),
                "followers": [f.to_dict() for f in followers],
            }
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)

            print(f"Wrote {len(followers)} followers to {output_path}")
            return 0

        if args.command == "scrape-following":
            # Determine output path
            if args.output:
                output_path = Path(args.output)
            else:
                # Default: data/<username>_following.json
                output_path = Path("data") / f"{args.username}_following.json"

            # Create parent directory if it doesn't exist
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Run scraping
            from social_media_scraper.instagram.scraper import scrape_following
            following_count_text, following = scrape_following(
                username=args.username,
                limit=args.limit,
                session_dir=Path(args.session_dir),
            )

            # Write output JSON
            import json
            output_data = {
                "target_username": args.username,
                "following_count_text": following_count_text,
                "scraped_count": len(following),
                "following": [f.to_dict() for f in following],
            }
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)

            print(f"Wrote {len(following)} following accounts to {output_path}")
            return 0

        if args.command == "scrape-feed":
            from datetime import date

            # Parse date filters
            parsed_from_date = None
            if args.from_date:
                try:
                    parsed_from_date = date.fromisoformat(args.from_date)
                except ValueError:
                    print(f"Error: Invalid --from-date format '{args.from_date}', expected YYYY-MM-DD", file=sys.stderr)
                    return 1

            parsed_to_date = None
            if args.to_date:
                try:
                    parsed_to_date = date.fromisoformat(args.to_date)
                except ValueError:
                    print(f"Error: Invalid --to-date format '{args.to_date}', expected YYYY-MM-DD", file=sys.stderr)
                    return 1

            # Determine output path
            output_path = Path(args.output) if args.output else Path("data/feed.json")
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Run scraping
            from social_media_scraper.instagram.scraper import scrape_feed
            posts = scrape_feed(
                limit=max(args.limit, 1),
                session_dir=Path(args.session_dir),
                from_date=parsed_from_date,
                to_date=parsed_to_date,
            )

            # Write output JSON - for feed, we just have posts, no profile
            import json
            output_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "scraped_at": str(date.today()),
                "post_count": len(posts),
                "posts": [post.to_dict() for post in posts],
            }
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)

            downloaded = 0
            if args.download_media:
                from social_media_scraper.instagram.storage import download_post_media
                media_dir = Path(args.media_dir) if args.media_dir else Path("data/feed_media")
                downloaded = download_post_media(posts, media_dir)

            print(f"Wrote {len(posts)} feed posts to {output_path}")
            if args.download_media:
                print(f"Downloaded {downloaded} media files")
            return 0
    except (BrowserSessionError, ScrapeError, URLError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    parser.print_help()
    return 1
