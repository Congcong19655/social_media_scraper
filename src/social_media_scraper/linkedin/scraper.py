"""
LinkedIn scraper wrapper that exposes profile scraping with session handling.
"""
import json
import os
from typing import Optional, Dict, Any, List
from pathlib import Path
from loguru import logger
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from .scrapers.person import PersonScraper
from .scrapers.connections import ConnectionsScraper
from .models.person import Person as LinkedInPerson
from .models.connection import Connection as LinkedInConnection


class LinkedInScraper:
    """LinkedIn profile scraper with session persistence."""

    def __init__(self, session_file: str, headless: bool = False):
        """Initialize with session file path."""
        self.session_file = Path(session_file)
        self.headless = headless
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    async def _initialize_browser(self) -> None:
        """Initialize browser and load session cookies if available."""
        playwright = await async_playwright().start()
        browser_args = [
            "--disable-blink-features=AutomationControlled",
            "--exclude-switches=enable-automation",
        ]
        if self.headless:
            browser_args.extend([
                "--headless=new",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
            ])
        self._browser = await playwright.chromium.launch(
            headless=self.headless,
            slow_mo=50,
            args=browser_args,
        )

        if self.session_file.exists():
            # Load existing session
            with open(self.session_file, "r", encoding="utf-8") as f:
                storage_state = json.load(f)
            self._context = await self._browser.new_context(
                storage_state=storage_state
            )
        else:
            # New session
            self._context = await self._browser.new_context()

        # Set longer default timeout (2 minutes)
        self._context.set_default_timeout(120000)
        self._page = await self._context.new_page()
        logger.info("Browser initialized")

    async def scrape_profile(self, profile_identifier: str) -> Dict[str, Any]:
        """
        Scrape a LinkedIn profile.

        Args:
            profile_identifier: LinkedIn profile URL OR just the username
                (e.g., "zhuminghui17" or "https://www.linkedin.com/in/zhuminghui17")

        Returns:
            Scraped profile data as dictionary
        """
        if not self._page:
            await self._initialize_browser()

        # Convert username to full URL if needed
        if profile_identifier.startswith("http"):
            profile_url = profile_identifier
        else:
            # Assume it's a username, build the full URL
            profile_url = f"https://www.linkedin.com/in/{profile_identifier}"

        scraper = PersonScraper(self._page)
        person_data = await scraper.scrape(profile_url)

        # Convert to dictionary
        result = self._person_to_dict(person_data)
        logger.info(f"Successfully scraped profile: {result.get('name', 'unknown')}")

        return result

    def _person_to_dict(self, person: LinkedInPerson) -> Dict[str, Any]:
        """Convert LinkedInPerson model to dictionary."""
        # Collect experiences with correct field names from the actual model
        experiences = []
        for exp in (person.experiences or []):
            experiences.append({
                "title": exp.position_title,
                "company": exp.institution_name,
                "location": exp.location,
                "start_date": exp.from_date,
                "end_date": exp.to_date,
                "description": exp.description,
            })

        # Collect education with correct field names
        education = []
        for edu in (person.educations or []):
            education.append({
                "school": edu.institution_name,
                "degree": edu.degree,
                "field_of_study": edu.description,
                "start_date": edu.from_date,
                "end_date": edu.to_date,
            })

        return {
            "name": person.name,
            "location": person.location,
            "about": person.about,
            "profile_url": person.linkedin_url,
            "open_to_work": person.open_to_work,
            "experiences": experiences,
            "education": education,
            "interests": [interest.name for interest in (person.interests or [])],
            "accomplishments": [
                {
                    "category": acc.category,
                    "title": acc.title,
                    "issuer": acc.issuer,
                } for acc in (person.accomplishments or [])
            ],
            "contacts": [
                {
                    "type": contact.type,
                    "value": contact.value,
                    "label": contact.label,
                } for contact in (person.contacts or [])
            ],
        }

    def _connection_to_dict(self, connection: LinkedInConnection) -> Dict[str, Any]:
        """Convert LinkedInConnection model to dictionary."""
        return {
            "profile_url": connection.profile_url,
            "profile_username": connection.profile_username,
        }

    async def scrape_connections(self, max_scrolls: int = 500, max_connections: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Scrape LinkedIn connections list.

        Args:
            max_scrolls: Maximum number of scroll attempts to load all connections
            max_connections: Maximum number of connections to scrape (None = all)

        Returns:
            List of connection dictionaries
        """
        if not self._page:
            await self._initialize_browser()

        scraper = ConnectionsScraper(self._page)
        connections = await scraper.scrape(max_scrolls=max_scrolls, max_connections=max_connections)

        # Convert to dictionaries
        result = [self._connection_to_dict(conn) for conn in connections]
        logger.info(f"Successfully scraped {len(result)} connections")

        return result

    async def save_session(self) -> None:
        """Save current browser session to file."""
        if self._context:
            self.session_file.parent.mkdir(parents=True, exist_ok=True)
            storage_state = await self._context.storage_state()
            with open(self.session_file, "w", encoding="utf-8") as f:
                json.dump(storage_state, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved session to {self.session_file}")

    async def close(self) -> None:
        """Close browser and clean up."""
        if self._browser:
            await self._browser.close()
            self._browser = None
            self._context = None
            self._page = None

    async def __aenter__(self):
        await self._initialize_browser()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
