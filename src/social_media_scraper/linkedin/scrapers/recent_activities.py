import logging
import re
from typing import List, Optional
from playwright.async_api import Page

from ..models.activity import Activity
from ..callbacks import ProgressCallback, SilentCallback
from .base import BaseScraper

logger = logging.getLogger(__name__)


class RecentActivitiesScraper(BaseScraper):
    """Scraper for extracting recent activities from a LinkedIn user profile."""

    def __init__(self, page: Page, callback: Optional[ProgressCallback] = None):
        super().__init__(page, callback or SilentCallback())

    async def scrape(
        self,
        profile_url: str,
        limit: int = 20,
        activity_filter: Optional[str] = None
    ) -> List[Activity]:
        """
        Scrape recent activities from a LinkedIn profile.

        Args:
            profile_url: Base profile URL or full recent-activity URL
            limit: Maximum number of activities to scrape
            activity_filter: Filter by activity type - "all", "reactions", "posts"
                If None, defaults to "all"

        Returns:
            List of Activity objects
        """
        logger.info(f"Starting recent activities scraping: {profile_url}")
        await self.callback.on_start("recent_activities", profile_url)

        # Normalize filter
        if activity_filter is None:
            activity_filter = "all"

        # Build the proper URL
        activities_url = self._build_activities_url(profile_url, activity_filter)
        await self.navigate_and_wait(activities_url)
        await self.callback.on_progress("Navigated to activities page", 10)

        await self.check_rate_limit()
        await self._wait_for_activities_to_load()
        await self.callback.on_progress("Activities loaded", 20)

        activities = await self._scrape_activities(limit)
        await self.callback.on_progress(f"Scraped {len(activities)} activities", 100)
        await self.callback.on_complete("recent_activities", activities)

        logger.info(f"Successfully scraped {len(activities)} activities")
        return activities

    def _build_activities_url(self, profile_url: str, activity_filter: str) -> str:
        """Build the correct recent activities URL."""
        profile_url = profile_url.rstrip('/')

        # If it's already a recent-activity URL, use it as-is
        if '/recent-activity' in profile_url:
            return profile_url

        # Extract username from profile URL
        # Profile URL format: https://www.linkedin.com/in/{username}/
        match = re.search(r'linkedin\.com/in/([^/]+)', profile_url)
        if not match:
            # If we can't extract, just append the path
            if activity_filter == "all":
                return f"{profile_url}/recent-activity/all/"
            elif activity_filter == "reactions":
                return f"{profile_url}/recent-activity/reactions/"
            elif activity_filter == "posts":
                return f"{profile_url}/recent-activity/all/"  # Posts are in all with different display
            else:
                return f"{profile_url}/recent-activity/all/"

        username = match.group(1)

        if activity_filter == "reactions":
            return f"https://www.linkedin.com/in/{username}/recent-activity/reactions/"
        else:  # "all" or "posts"
            return f"https://www.linkedin.com/in/{username}/recent-activity/all/"

    async def _wait_for_activities_to_load(self, timeout: int = 30000) -> None:
        """Wait for activities to load on the page."""
        try:
            await self.page.wait_for_load_state('domcontentloaded', timeout=timeout)
        except Exception as e:
            logger.debug(f"DOM load timeout: {e}")

        await self.page.wait_for_timeout(3000)

        for attempt in range(3):
            await self._trigger_lazy_load()

            has_activities = await self.page.evaluate('''() => {
                return document.body.innerHTML.includes('urn:li:activity:');
            }''')

            if has_activities:
                logger.debug(f"Activities found after attempt {attempt + 1}")
                return

            await self.page.wait_for_timeout(2000)

        logger.warning("Activities may not have loaded fully")

    async def _trigger_lazy_load(self) -> None:
        """Trigger lazy loading by scrolling."""
        await self.page.evaluate('''() => {
            const scrollHeight = document.documentElement.scrollHeight;
            const steps = 8;
            const stepSize = Math.min(scrollHeight / steps, 400);

            for (let i = 1; i <= steps; i++) {
                setTimeout(() => window.scrollTo(0, stepSize * i), i * 200);
            }
        }''')
        await self.page.wait_for_timeout(2500)

        await self.page.evaluate('window.scrollTo(0, 400)')
        await self.page.wait_for_timeout(1000)

    async def _scrape_activities(self, limit: int) -> List[Activity]:
        """Scrape activities with scrolling until we reach the limit."""
        activities: List[Activity] = []
        scroll_count = 0
        max_scrolls = (limit // 3) + 2

        while len(activities) < limit and scroll_count < max_scrolls:
            new_activities = await self._extract_activities_from_page()

            for activity in new_activities:
                if activity.urn and not any(a.urn == activity.urn for a in activities):
                    activities.append(activity)
                    if len(activities) >= limit:
                        break

            if len(activities) < limit:
                await self._scroll_for_more()
                scroll_count += 1

        return activities[:limit]

    async def _extract_activities_from_page(self) -> List[Activity]:
        """Extract all activities currently visible on the page."""
        return await self._extract_activities_via_js()

    async def _extract_activities_via_js(self) -> List[Activity]:
        """Extract activities using JavaScript evaluation for better performance."""
        activities_data = await self.page.evaluate('''() => {
            const activities = [];
            const html = document.body.innerHTML;

            // Find all activity URNs in the page
            const urnMatches = html.matchAll(/urn:li:activity:(\\d+)/g);
            const seenUrns = new Set();

            for (const match of urnMatches) {
                const urn = match[0];
                if (seenUrns.has(urn)) continue;
                seenUrns.add(urn);

                // Find the element with this URN
                const el = document.querySelector(`[data-urn="${urn}"]`);
                if (!el) continue;

                // Determine activity type by looking at the header
                let activityType = 'original_post';
                let reactionType = null;

                // Check for reaction indicator
                const headerText = el.innerText || '';
                if (headerText.includes("reacted to") || headerText.includes("reacted on")) {
                    activityType = 'reaction';
                } else if (headerText.includes("reposted")) {
                    activityType = 'repost';
                }

                // Get text content - try multiple selectors
                let text = '';
                const textSelectors = [
                    '.feed-shared-update-v2__description',
                    '.update-components-text',
                    '.feed-shared-text',
                    '[data-test-id="main-feed-activity-card__commentary"]',
                    '.break-words.whitespace-pre-wrap'
                ];

                for (const sel of textSelectors) {
                    const textEl = el.querySelector(sel);
                    if (textEl) {
                        const t = textEl.innerText?.trim() || '';
                        if (t.length > text.length && t.length > 20) {
                            // Skip the header text that says "X reacted to"
                            if (!t.match(/^.* reacted to/) && !t.match(/^.* reposted/)) {
                                text = t;
                            }
                        }
                    }
                }

                // Get original author info for reactions/reposts
                let originalAuthorName = null;
                let originalAuthorProfileUrl = null;
                let originalPostUrn = null;

                if (activityType === 'reaction' || activityType === 'repost') {
                    // Find the original post inside this activity
                    const originalPostEl = el.querySelector('[data-urn]');
                    if (originalPostEl && originalPostEl !== el) {
                        originalPostUrn = originalPostEl.getAttribute('data-urn');
                    }

                    // Look for author link
                    const authorLink = el.querySelector('.update-components-actor__container a');
                    if (authorLink) {
                        originalAuthorName = authorLink.textContent?.trim() || null;
                        originalAuthorProfileUrl = authorLink.getAttribute('href');
                        if (originalAuthorProfileUrl && !originalAuthorProfileUrl.startsWith('http')) {
                            originalAuthorProfileUrl = 'https://www.linkedin.com' + originalAuthorProfileUrl;
                        }
                    }
                }

                // Get time
                const timeEl = el.querySelector('[class*="actor__sub-description"], [class*="update-components-actor__sub-description"]');
                const timeText = timeEl ? timeEl.innerText : '';

                // Get reactions
                let reactionsText = '';
                const reactionsEl = el.querySelector('button[aria-label*="reaction"], [class*="social-details-social-counts__reactions"]');
                if (reactionsEl) {
                    reactionsText = reactionsEl.innerText;
                }

                // Get comments
                let commentsText = '';
                const commentsEl = el.querySelector('button[aria-label*="comment"]');
                if (commentsEl) {
                    commentsText = commentsEl.innerText;
                }

                // Get reposts
                let repostsText = '';
                const repostsEl = el.querySelector('button[aria-label*="repost"]');
                if (repostsEl) {
                    repostsText = repostsEl.innerText;
                }

                // Get images
                const images = [];
                el.querySelectorAll('img[src*="media"]').forEach(img => {
                    if (img.src && !img.src.includes('profile') && !img.src.includes('logo')) {
                        images.push(img.src);
                    }
                });

                activities.push({
                    urn: urn,
                    activityType: activityType,
                    reactionType: reactionType,
                    text: text ? text.substring(0, 3000) : '',
                    timeText: timeText,
                    reactions: reactionsText,
                    comments: commentsText,
                    reposts: repostsText,
                    images: images,
                    originalAuthorName: originalAuthorName,
                    originalAuthorProfileUrl: originalAuthorProfileUrl,
                    originalPostUrn: originalPostUrn
                });
            }

            return activities;
        }''')

        result: List[Activity] = []
        for data in activities_data:
            activity_id = data['urn'].replace('urn:li:activity:', '')
            activity_url = f"https://www.linkedin.com/feed/update/urn:li:activity:{activity_id}/"

            original_post_urn = data.get('originalPostUrn')
            original_post_url = None
            if original_post_urn and 'urn:li:activity:' in original_post_urn:
                original_activity_id = original_post_urn.replace('urn:li:activity:', '')
                original_post_url = f"https://www.linkedin.com/feed/update/urn:li:activity:{original_activity_id}/"

            activity = Activity(
                linkedin_url=activity_url,
                urn=data['urn'],
                activity_type=data.get('activityType'),
                reaction_type=data.get('reactionType'),
                text=data.get('text') or None,
                posted_date=self._extract_time_from_text(data.get('timeText', '')),
                reactions_count=self._parse_count(data.get('reactions', '')),
                comments_count=self._parse_count(data.get('comments', '')),
                reposts_count=self._parse_count(data.get('reposts', '')),
                image_urls=data.get('images', []),
                original_author_name=data.get('originalAuthorName'),
                original_author_profile_url=data.get('originalAuthorProfileUrl'),
                original_post_urn=original_post_urn,
                original_post_url=original_post_url
            )
            result.append(activity)

        return result

    def _extract_time_from_text(self, text: str) -> Optional[str]:
        """Extract relative time from text."""
        if not text:
            return None
        match = re.search(r'(\d+[hdwmy]|\d+\s*(?:hour|day|week|month|year)s?\s*ago)', text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        parts = text.split('•')
        if parts:
            return parts[0].strip()
        return None

    def _parse_count(self, text: str) -> Optional[int]:
        """Parse count from social stats text."""
        if not text:
            return None
        try:
            numbers = re.findall(r'[\d,]+', text.replace(',', ''))
            if numbers:
                return int(numbers[0])
        except:
            pass
        return None

    async def _scroll_for_more(self) -> None:
        """Scroll to load more activities."""
        try:
            await self.page.keyboard.press('End')
            await self.page.wait_for_timeout(1500)
        except Exception as e:
            logger.debug(f"Error scrolling: {e}")
