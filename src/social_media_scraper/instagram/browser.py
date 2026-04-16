from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from social_media_scraper.instagram.selectors import LOGIN_PATH_SNIPPETS

try:
    from playwright.sync_api import BrowserContext, Page, sync_playwright
except ImportError:  # pragma: no cover - exercised when dependency is missing
    BrowserContext = object  # type: ignore[assignment]
    Page = object  # type: ignore[assignment]
    sync_playwright = None


class BrowserSessionError(RuntimeError):
    """Raised when the browser session is missing or invalid."""


def login_instagram(session_dir: Path) -> None:
    _login_site(
        session_dir=session_dir,
        login_url="https://www.instagram.com/accounts/login/",
        home_url="https://www.instagram.com/",
        platform_name="Instagram",
        login_markers=LOGIN_PATH_SNIPPETS,
    )


@contextmanager
def persistent_context(session_dir: Path, *, headless: bool = False) -> Iterator[BrowserContext]:
    _require_playwright()
    session_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(session_dir),
            headless=headless,
            viewport={"width": 1440, "height": 1200},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--exclude-switches=enable-automation",
                "--no-first-run",
            ],
        )
        context.set_default_timeout(120000)  # 2 minutes default timeout
        try:
            yield context
        finally:
            context.close()


@contextmanager
def authenticated_context(session_dir: Path, *, headless: bool = False) -> Iterator[BrowserContext]:
    if not session_dir.exists():
        raise BrowserSessionError(
            f"No saved Instagram session found at {session_dir}. Run `uv run python run.py login-instagram` first."
        )
    with persistent_context(session_dir, headless=headless) as context:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=120000)
        if not is_logged_in(page):
            raise BrowserSessionError(
                "Saved session is not currently logged in. Instagram redirected to login or checkpoint."
            )
        yield context


def is_logged_in(page: Page) -> bool:
    return _is_logged_in(page, LOGIN_PATH_SNIPPETS, "Log in")


def _require_playwright() -> None:
    if sync_playwright is None:
        raise BrowserSessionError(
            "Playwright is not installed. Run `uv sync` and `uv run playwright install chromium` first."
        )


def _login_site(
    *,
    session_dir: Path,
    login_url: str,
    home_url: str,
    platform_name: str,
    login_markers: tuple[str, ...],
) -> None:
    # Login is always headed - you need to interact
    with persistent_context(session_dir) as context:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(login_url, wait_until="domcontentloaded", timeout=120000)
        print(f"A browser window is open for {platform_name} login.")
        print("Log in manually, finish any checkpoint prompts, then press Enter here to save the session.")
        input()
        page.goto(home_url, wait_until="domcontentloaded", timeout=120000)
        if not _is_logged_in(page, login_markers, "Log in"):
            raise BrowserSessionError(
                f"{platform_name} session was not saved. You may still be on the login, challenge, or checkpoint page."
            )
        print(f"\n✓ {platform_name} session saved to {session_dir}")


def _is_logged_in(page: Page, login_markers: tuple[str, ...], login_keyword: str) -> bool:
    url = page.url.lower()
    if any(snippet in url for snippet in login_markers):
        return False
    page_text = page.locator("body").inner_text(timeout=5000)
    return login_keyword not in page_text
