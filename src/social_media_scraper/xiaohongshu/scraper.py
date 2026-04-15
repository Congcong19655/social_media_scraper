"""
Xiaohongshu scraper wrapper that adapts the original Data_Spider to the unified interface.
Preserves all original logic but outputs JSON instead of Excel.
"""
import os
import urllib
from typing import Optional, List, Dict, Any
from datetime import datetime
from loguru import logger

from .apis.xhs_pc_apis import XHS_Apis
from .xhs_utils.data_util import handle_note_info


class XiaohongshuScraper:
    """Wrapper for the original Xiaohongshu Data_Spider."""

    def __init__(self, cookies: str, js_path: str):
        """Initialize the scraper with cookies."""
        self.cookies = cookies
        self.xhs_apis = XHS_Apis()
        # Update js path to our new location
        from .xhs_utils import common_util
        # Monkey patch to use our js directory
        common_util.X_SIGNATURE_JS_PATH = os.path.join(js_path, "xhs_creator_signature.js")
        common_util.X_SIGNATURE_OTHER_JS_PATH = os.path.join(js_path, "xhs_creator_sign_other.js")

    def _parse_user_url(self, user_url_or_handle: str) -> tuple[str, str, str]:
        """Parse user URL or handle to get user_id and tokens."""
        if not user_url_or_handle.startswith("http"):
            # Assume it's a username/handle, construct URL
            user_url_or_handle = f"https://www.xiaohongshu.com/user/profile/{user_url_or_handle}"

        url_parse = urllib.parse.urlparse(user_url_or_handle)
        user_id = url_parse.path.split('/')[-1]
        kvs = url_parse.query.split('&')
        kv_dist = {kv.split('=')[0]: kv.split('=')[1] for kv in kvs if '=' in kv}
        xsec_token = kv_dist.get('xsec_token', "")
        xsec_source = kv_dist.get('xsec_source', "pc_search")
        return user_id, xsec_token, xsec_source

    def scrape_user(
        self,
        user_identifier: str,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        download_media: bool = False,
        media_dir: Optional[str] = None,
        proxies: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Scrape all notes from a Xiaohongshu user with date filtering.

        Args:
            user_identifier: User URL or user ID/handle
            from_date: YYYY-MM-DD, earliest note to include
            to_date: YYYY-MM-DD, latest note to include
            download_media: Whether to download media (images/videos)
            media_dir: Directory to save downloaded media
            proxies: Optional proxy configuration

        Returns:
            Dict with scraped notes and metadata
        """
        user_id, xsec_token, xsec_source = self._parse_user_url(user_identifier)
        logger.info(f"Starting scrape for Xiaohongshu user {user_id}")

        all_notes: List[Dict[str, Any]] = []
        cursor = ''
        total_fetched = 0
        filtered_out = 0
        pinned_encountered = 0
        max_pinned_notes = 5
        early_stopped = False

        start_obj = datetime.strptime(from_date, "%Y-%m-%d") if from_date else None
        end_obj = datetime.strptime(to_date, "%Y-%m-%d") if to_date else None

        while True:
            success, msg, res_json = self.xhs_apis.get_user_note_info(
                user_id, cursor, self.cookies, xsec_token, xsec_source, proxies
            )
            if not success:
                logger.error(f"Failed to fetch user notes page: {msg}")
                break

            notes_page = res_json["data"].get("notes", [])
            if not notes_page:
                logger.info(f"No more notes found for user {user_id}")
                break

            page_has_in_range = False

            for simple_note_info in notes_page:
                note_url = f"https://www.xiaohongshu.com/explore/{simple_note_info['note_id']}"
                if 'xsec_token' in simple_note_info and simple_note_info['xsec_token']:
                    note_url += f"?xsec_token={simple_note_info['xsec_token']}"

                success_detail, msg_detail, note_info = self._spider_note(note_url, proxies)
                if note_info is None or not success_detail:
                    continue

                total_fetched += 1

                # Apply date filtering
                include_note = True
                note_date_str = note_info['upload_time'].split(' ')[0]
                note_date = datetime.strptime(note_date_str, "%Y-%m-%d")

                if start_obj and note_date < start_obj:
                    # Allow older pinned notes
                    if pinned_encountered < max_pinned_notes:
                        pinned_encountered += 1
                        logger.info(f"Keeping older pinned note ({pinned_encountered}/{max_pinned_notes})")
                    else:
                        filtered_out += 1
                        include_note = False
                        if not page_has_in_range:
                            page_has_in_range = True
                    if include_note is False:
                        continue
                elif start_obj:
                    page_has_in_range = True

                if end_obj and include_note:
                    if note_date > end_obj:
                        filtered_out += 1
                        include_note = False

                if include_note:
                    if download_media and media_dir:
                        from .xhs_utils.data_util import download_note
                        os.makedirs(media_dir, exist_ok=True)
                        download_note(note_info, media_dir, "all")
                    all_notes.append(note_info)

            # Check for early stopping when date filtering
            if from_date and not page_has_in_range and len(notes_page) > 0:
                logger.info("All notes on this page are before start_date, stopping early")
                early_stopped = True
                break

            # Get next cursor
            cursor = res_json["data"].get("cursor", "")
            if not cursor:
                break

        logger.info(
            f"Xiaohongshu scrape completed: fetched {total_fetched} notes, "
            f"filtered {filtered_out}, kept {len(all_notes)}"
        )

        return {
            "user_id": user_id,
            "total_fetched": total_fetched,
            "filtered_out": filtered_out,
            "early_stopped": early_stopped,
            "notes": all_notes,
        }

    def _spider_note(self, note_url: str, proxies=None) -> tuple[bool, str, Optional[Dict[str, Any]]]:
        """Spider a single note's detailed info."""
        note_info = None
        try:
            success, msg, note_info = self.xhs_apis.get_note_info(note_url, self.cookies, proxies)
            if success:
                note_info = note_info['data']['items'][0]
                note_info['url'] = note_url
                note_info = handle_note_info(note_info)
        except Exception as e:
            success = False
            msg = str(e)
            logger.error(f"Error scraping note {note_url}: {e}")
        return success, msg, note_info
