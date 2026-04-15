import os
from typing import Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv


class BrowserConfig(BaseModel):
    """Browser configuration."""
    headless: bool = False
    slow_mo: int = 50
    timeout: int = 60000


class XiaohongshuConfig(BaseModel):
    """Xiaohongshu configuration."""
    cookies: Optional[str] = Field(None, description="XHS cookies from .env")
    js_path: str = Field(description="Path to JS signature files")


class InstagramConfig(BaseModel):
    """Instagram configuration."""
    session_dir: str = Field(description="Persistent session directory")


class LinkedInConfig(BaseModel):
    """LinkedIn configuration."""
    session_file: str = Field(description="Session cookies file path")


class Config(BaseModel):
    """Global configuration loaded from environment."""
    browser: BrowserConfig
    xiaohongshu: XiaohongshuConfig
    instagram: InstagramConfig
    linkedin: LinkedInConfig


def load_config(project_root: str) -> Config:
    """Load configuration from .env file."""
    load_dotenv(os.path.join(project_root, ".env"))

    return Config(
        browser=BrowserConfig(
            headless=os.getenv("BROWSER_HEADLESS", "false").lower() == "true",
        ),
        xiaohongshu=XiaohongshuConfig(
            cookies=os.getenv("XHS_COOKIES"),
            js_path=os.path.join(project_root, "src", "social_media_scraper", "xiaohongshu", "js"),
        ),
        instagram=InstagramConfig(
            session_dir=os.path.join(project_root, "sessions", "instagram"),
        ),
        linkedin=LinkedInConfig(
            session_file=os.path.join(project_root, "sessions", "linkedin", "session.json"),
        ),
    )
