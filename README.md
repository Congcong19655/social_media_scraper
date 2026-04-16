# Unified Social Media Scraper

Combined scraper for Xiaohongshu, Instagram, and LinkedIn in a single CLI tool.

## Features

- Reads a single account list CSV with all platforms
- One-time interactive login for all platforms (persists cookies/sessions)
- Date filtering for Xiaohongshu and Instagram posts
- JSON output only (organized by account)
- Preserves all original scraper logic
- Built-in lead generation with LLM (Doubao/ByteDance Ark)

## Requirements

- Python 3.10+
- Node.js (for Xiaohongshu signature generation)
- `uv` (Python package manager)

## Installation

1. Clone the project:
```bash
cd social-media-scraper
```

1. Install Python dependencies (use `uv` for best results):
```bash
uv sync
```

If you don't have uv, you can use pip with a virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install pydantic python-dotenv click loguru aiofiles aiohttp pandas PyExecJS retry opencv-python numpy qrcode openpyxl playwright beautifulsoup4 requests lxml openai volcengine-python-sdk[ark]
```

3. Install Node.js dependencies:
```bash
npm install
```

4. Install Playwright browsers:
```bash
# If using uv
uv run playwright install chromium

# If not using uv, activate your virtual environment first then:
# playwright install chromium
```

5. Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

## Setup Authentication

Login to each platform once to save credentials:

```bash
# Login to Xiaohongshu (saves cookies to .env)
uv run run.py login-xiaohongshu

# Login to Instagram (saves persistent session)
uv run run.py login-instagram

# Login to LinkedIn (saves persistent session)
uv run run.py login-linkedin
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
uv run run.py scrape \
  --accounts accounts/example.csv \
  --output data/ \
  --from-date 2025-04-01 \
  --to-date 2025-12-31 \
  --download-media
```

Options:
- `--accounts`: Path to your accounts CSV (required)
- `--output`: Output directory for JSON results (required)
- `--from-date`: Only include posts on or after this date (YYYY-MM-DD, optional)
- `--to-date`: Only include posts on or before this date (YYYY-MM-DD, optional)
- `--download-media`: Download images/videos (optional, saves to `media/`)

## Generate Leads

After scraping, you can generate lead insights using the built-in Doubao/LLM processor:

```bash
uv run run.py generate-leads \
  --input data/ \
  --output leads/ \
  --from-date 2025-04-01 \
  --to-date 2025-12-31 \
  [--account "Account Name"] \
  [--no-json]
```

Options:
- `--input`: Input directory with scraped JSON data (usually `data/`, required)
- `--output`: Output directory for lead results (usually `leads/`, required)
- `--from-date`: Filter content after this date (YYYY-MM-DD, optional)
- `--to-date`: Filter content before this date (YYYY-MM-DD, optional)
- `--account`: Only process a specific account (for testing, optional)
- `--no-json`: Don't save JSON output, only markdown (optional)

**Note:** You need to configure `DOUBAO_API_KEY` and `DOUBAO_ENDPOINT` in your `.env` file for lead generation.

## End-to-End Pipeline

You can run the complete pipeline (clean + scrape + generate leads) in one command:

```bash
uv run run.py pipeline \
  --accounts accounts/example.csv \
  --from-date 2025-04-01 \
  --to-date 2025-12-31 \
  --download-media \
  [--no-clean]
```

Options:
- `--accounts`: Path to your accounts CSV (required)
- `--from-date`: Start date (YYYY-MM-DD, optional)
- `--to-date`: End date (YYYY-MM-DD, optional)
- `--download-media`: Download images/videos (optional)
- `--no-clean`: Skip cleaning data/media folders before run (optional)

This will:
1. Clean up `data/` and `media/` folders (unless `--no-clean`)
2. Scrape all accounts
3. Generate lead summaries with LLM

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
├── linkedin/           # LinkedIn scraper (imported from linkedin_scraper)
└── lead_generator/     # LLM-based lead extraction (Doubao/ByteDance Ark)
```

## Notes

- Xiaohongshu still requires Node.js for signature generation (this is preserved from original)
- All original scraping logic is kept intact, only wrapped with a unified interface
- If scraping fails for one platform/account, it continues with the next
- Sessions persist between runs, you don't need to login every time

## Acknowledgments

This project incorporates code from the following open-source projects:

- **Spider_XHS** (Xiaohongshu scraper): https://github.com/cv-cat/Spider_XHS - MIT License
- **linkedin_scraper** (LinkedIn scraper): https://github.com/joeyism/linkedin_scraper - Apache License 2.0

## License

This project follows the licenses of the incorporated components:
- Xiaohongshu scraper portion: MIT License
- LinkedIn scraper portion: Apache License 2.0
