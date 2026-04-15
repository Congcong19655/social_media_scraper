import json
import os
from typing import Any
from datetime import datetime
from pathlib import Path
from loguru import logger

from .models import Account, AccountMetadata, PlatformResult


def ensure_account_dir(output_dir: str, account_name: str) -> Path:
    """Ensure output directory exists for the account."""
    account_dir = Path(output_dir) / _clean_filename(account_name)
    account_dir.mkdir(parents=True, exist_ok=True)
    return account_dir


def _clean_filename(name: str) -> str:
    """Clean account name for use as directory filename."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)


def save_platform_output(
    account_dir: Path,
    result: PlatformResult,
) -> None:
    """Save platform-specific result to JSON."""
    platform_file = account_dir / f"{result.platform}.json"
    with open(platform_file, "w", encoding="utf-8") as f:
        json.dump({
            "platform": result.platform,
            "account_handle": result.account_handle,
            "scraped_at": result.scraped_at.isoformat(),
            "items_count": result.items_count,
            "success": result.success,
            "error": result.error,
            "data": result.data,
        }, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved {result.platform} output to {platform_file}")


def save_metadata(
    output_dir: str,
    account: Account,
    metadata: AccountMetadata,
) -> None:
    """Save combined metadata for an account scrape."""
    account_dir = ensure_account_dir(output_dir, account.name)
    metadata_file = account_dir / "metadata.json"
    with open(metadata_file, "w", encoding="utf-8") as f:
        json.dump({
            "account_name": metadata.account_name,
            "scraped_at": metadata.scraped_at.isoformat(),
            "from_date": metadata.from_date,
            "to_date": metadata.to_date,
            "platforms_scraped": metadata.platforms_scraped,
            "platform_results": {
                name: {
                    "platform": p.platform,
                    "account_handle": p.account_handle,
                    "scraped_at": p.scraped_at.isoformat(),
                    "items_count": p.items_count,
                    "success": p.success,
                    "error": p.error,
                } for name, p in metadata.platform_results.items()
            },
        }, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved metadata to {metadata_file}")


def load_accounts_from_csv(csv_path: str) -> list[Account]:
    """Load accounts from a CSV file."""
    import pandas as pd
    df = pd.read_csv(csv_path)
    accounts = []
    for _, row in df.iterrows():
        account = Account(
            name=str(row["name"]),
            instagram=row.get("instagram") if pd.notna(row.get("instagram")) else None,
            xiaohongshu=row.get("xiaohongshu") if pd.notna(row.get("xiaohongshu")) else None,
            linkedin=row.get("linkedin") if pd.notna(row.get("linkedin")) else None,
        )
        # Strip whitespace
        if account.instagram:
            account.instagram = account.instagram.strip()
        if account.xiaohongshu:
            account.xiaohongshu = account.xiaohongshu.strip()
        if account.linkedin:
            account.linkedin = account.linkedin.strip()
        accounts.append(account)
    logger.info(f"Loaded {len(accounts)} accounts from {csv_path}")
    return accounts
