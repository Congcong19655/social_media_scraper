# Unified Social Media Scraper

Combined scraper for Xiaohongshu, Instagram, and LinkedIn in a single CLI tool.

## Features

- Reads a single account list CSV with all platforms
- One-time interactive login for all platforms (persists cookies/sessions)
- Date filtering for Xiaohongshu and Instagram posts
- JSON output only (organized by account)
- Preserves all original scraper logic

## Requirements

- Python 3.10+
- Node.js (for Xiaohongshu signature generation)
- `uv` (Python package manager)

## Installation

1. Clone or create the project:
```bash
cd social-media-scraper
```

2. Install Python dependencies:
```bash
uv sync
```

3. Install Node.js dependencies:
```bash
npm install
```

4. Install Playwright browsers:
```bash
uv run playwright install chromium
```

5. Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

## Setup Authentication

Login to each platform once to save credentials:

```bash
# Login to Xiaohongshu (saves cookies to .env)
uv run social-media-scraper login-xiaohongshu

# Login to Instagram (saves persistent session)
uv run social-media-scraper login-instagram

# Login to LinkedIn (saves persistent session)
uv run social-media-scraper login-linkedin
```

Follow the interactive prompts - scan QR code / login manually in the browser, then press Enter to save the session.

## Prepare Account List

Create a CSV file (or use `accounts/example.csv`):

```csv
name,instagram,xiaohongshu,linkedin
Account Name,instagram_handle,xiaohongshu_user_id,https://www.linkedin.com/in/profile
```

- `name`: Account name (required, used for output directory)
- `instagram`: Instagram username (optional, leave empty to skip)
- `xiaohongshu`: Xiaohongshu user ID or URL (optional, leave empty to skip)
- `linkedin`: LinkedIn profile URL (optional, leave empty to skip)

## Usage

```bash
uv run social-media-scraper scrape \
  --accounts accounts/your_accounts.csv \
  --output data/ \
  --from-date 2024-01-01 \
  --to-date 2024-12-31 \
  [--download-media]
```

Options:
- `--accounts`: Path to your accounts CSV (required)
- `--output`: Output directory for JSON results (required)
- `--from-date`: Only include posts on or after this date (YYYY-MM-DD, optional)
- `--to-date`: Only include posts on or before this date (YYYY-MM-DD, optional)
- `--download-media`: Download images/videos (optional, saves to `media/`)

## Output Structure

```
data/
└── {account_name}/
    ├── metadata.json      # Combined metadata
    ├── instagram.json     # Instagram posts
    ├── xiaohongshu.json   # Xiaohongshu notes
    └── linkedin.json      # LinkedIn profile data
```

If media download is enabled, media files go to:
```
media/
└── {account_name}/
    ├── instagram/
    └── xiaohongshu/
```

## Project Structure

```
src/social_media_scraper/
├── cli.py              # Unified CLI entry point
├── models.py           # Common Pydantic models
├── config.py           # Configuration loading
├── output.py           # JSON output handling
├── xiaohongshu/        # Xiaohongshu scraper (imported from Spider_XHS)
├── instagram/          # Instagram scraper (imported from social_listening)
└── linkedin/           # LinkedIn scraper (imported from linkedin_scraper)
```

## Notes

- Xiaohongshu still requires Node.js for signature generation (this is preserved from original)
- All original scraping logic is kept intact, only wrapped with a unified interface
- If scraping fails for one platform/account, it continues with the next
- Sessions persist between runs, you don't need to login every time

## License

Same as original individual repositories.
