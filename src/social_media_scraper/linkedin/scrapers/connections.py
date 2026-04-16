"""Connections scraper for LinkedIn."""

import asyncio
from typing import List, Optional, Set
from urllib.parse import urljoin
from playwright.async_api import Page
from loguru import logger

from .base import BaseScraper
from ..models import Connection
from ..callbacks import ProgressCallback, SilentCallback
from ..core.exceptions import ScrapingError


class ConnectionsScraper(BaseScraper):
    """Async scraper for LinkedIn connections list."""

    CONNECTIONS_URL = "https://www.linkedin.com/mynetwork/invite-connect/connections/"

    def __init__(self, page: Page, callback: Optional[ProgressCallback] = None):
        """
        Initialize connections scraper.

        Args:
            page: Playwright page object
            callback: Progress callback
        """
        super().__init__(page, callback)

    async def scrape(self, max_scrolls: int = 500, max_connections: Optional[int] = None) -> List[Connection]:
        """
        Scrape LinkedIn connections list.

        Args:
            max_scrolls: Maximum number of scroll attempts to load all connections
            max_connections: Maximum number of connections to scrape (None = all)

        Returns:
            List of Connection objects

        Raises:
            AuthenticationError: If not logged in
            ScrapingError: If scraping fails
        """
        await self.callback.on_start("connections", self.CONNECTIONS_URL)

        try:
            # First navigate to LinkedIn homepage to warm up the session
            logger.info("Warming up session by navigating to LinkedIn homepage...")
            await self.page.goto("https://www.linkedin.com/", wait_until="domcontentloaded", timeout=60000)
            await self.wait_and_focus(2)

            # Now navigate to connections page
            logger.info(f"Navigating to connections page: {self.CONNECTIONS_URL}")
            await self.page.goto(self.CONNECTIONS_URL, wait_until="domcontentloaded", timeout=60000)
            await self.callback.on_progress("Navigated to connections page", 10)
            await self.wait_and_focus(3)

            # Check if logged in
            await self.ensure_logged_in()
            await self.callback.on_progress("Logged in verified", 20)

            # Extract connections by scrolling the main container with JavaScript
            logger.info("Starting to scroll through connections list...")
            connections = await self._extract_connections_with_js_scroll(max_scrolls, max_connections)
            await self.callback.on_progress(f"Extracted {len(connections)} connections", 90)

            await self.callback.on_complete("connections", len(connections))
            return connections

        except Exception as e:
            logger.error(f"Failed to scrape connections: {e}", exc_info=True)
            await self.callback.on_error(e)
            raise ScrapingError(f"Failed to scrape connections: {e}") from e

    async def _extract_connections_with_js_scroll(self, max_scrolls: int = 5000, max_connections: Optional[int] = None) -> List[Connection]:
        """Extract connections using JavaScript to find and scroll the right container."""
        seen_profile_urls: Set[str] = set()
        connections: List[Connection] = []

        no_new_count = 0

        for scroll_attempt in range(max_scrolls):
            # Check if we've reached max_connections
            if max_connections is not None and len(connections) >= max_connections:
                logger.info(f"Reached max connections limit of {max_connections}, stopping...")
                break

            # Extract any new connections currently in the DOM
            new_connections = await self._extract_visible_connections(seen_profile_urls)
            for conn in new_connections:
                connections.append(conn)
                seen_profile_urls.add(conn.profile_url)

                # Check if we've reached max_connections after adding this one
                if max_connections is not None and len(connections) >= max_connections:
                    break

            if len(new_connections) > 0:
                logger.info(f"Collected {len(connections)} connections so far...")
                no_new_count = 0
            else:
                no_new_count += 1

            # If no new connections after many attempts, we're done
            if no_new_count >= 30:
                logger.info(f"No new connections after {no_new_count} attempts, stopping...")
                break

            # Try to scroll any scrollable container we can find
            await self._scroll_with_js()

            # Small pause to let content load
            await asyncio.sleep(0.2)

        logger.info(f"Finished extracting {len(connections)} connections")
        return connections

    async def _scroll_with_js(self) -> None:
        """Use JavaScript to find and scroll all scrollable containers."""
        try:
            await self.page.evaluate("""
                () => {
                    // Try to scroll all potential scrollable elements
                    const allElements = document.querySelectorAll('*');
                    for (const el of allElements) {
                        const style = window.getComputedStyle(el);
                        if (style.overflowY === 'scroll' || style.overflowY === 'auto' || el.scrollHeight > el.clientHeight + 100) {
                            el.scrollTop += 500;
                        }
                    }
                    // Also scroll the window
                    window.scrollBy(0, 500);
                }
            """)
        except Exception as e:
            logger.debug(f"JS scroll failed: {e}")

    async def _extract_visible_connections(self, seen_urls: Set[str]) -> List[Connection]:
        """Extract connections that are currently visible in the DOM."""
        new_connections: List[Connection] = []

        # Find all links to profiles
        profile_links = await self.page.locator('a[href*="/in/"]').all()

        for link in profile_links:
            try:
                href = await link.get_attribute("href")
                if not href:
                    continue

                # Clean up URL
                if href.startswith("/"):
                    href = urljoin("https://www.linkedin.com", href)
                if "?" in href:
                    href = href.split("?")[0]
                # Remove language suffix like /en/ or /zh/
                for lang_suffix in ["/en", "/zh", "/es", "/fr", "/de", "/ja", "/ko"]:
                    if href.endswith(lang_suffix):
                        href = href[:-len(lang_suffix)]
                    elif lang_suffix + "/" in href:
                        href = href.replace(lang_suffix + "/", "/")
                href = href.rstrip("/")

                # Skip if we already have this one
                if href in seen_urls:
                    continue

                # Skip non-profile links
                if "/in/" not in href:
                    continue

                # Create connection object - we don't need name anymore
                try:
                    conn = Connection(profile_url=href)
                    new_connections.append(conn)
                    seen_urls.add(href)
                except Exception:
                    continue

            except Exception:
                continue

        return new_connections
