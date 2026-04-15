from pydantic import BaseModel
from typing import Optional, Literal
from datetime import datetime


class Account(BaseModel):
    """Represents a single social media account to scrape."""
    name: str
    instagram: Optional[str] = None
    xiaohongshu: Optional[str] = None
    linkedin: Optional[str] = None


class ScrapeConfig(BaseModel):
    """Configuration for a scraping run."""
    accounts_file: str
    output_dir: str
    from_date: Optional[str] = None  # YYYY-MM-DD
    to_date: Optional[str] = None    # YYYY-MM-DD
    download_media: bool = False


class PlatformResult(BaseModel):
    """Result from scraping a single platform."""
    platform: Literal["instagram", "xiaohongshu", "linkedin"]
    account_handle: str
    scraped_at: datetime
    items_count: int
    data: list | dict
    success: bool
    error: Optional[str] = None


class AccountMetadata(BaseModel):
    """Combined metadata for an account scrape."""
    account_name: str
    scraped_at: datetime
    from_date: Optional[str] = None
    to_date: Optional[str] = None
    platforms_scraped: list[str]
    platform_results: dict[str, PlatformResult]
