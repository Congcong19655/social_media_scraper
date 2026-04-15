#!/usr/bin/env python3
"""Simple entry point to run the social media scraper without installation."""
import sys
import os

# Add src directory to Python path
src_dir = os.path.join(os.path.dirname(__file__), "src")
sys.path.insert(0, src_dir)

from social_media_scraper.cli import main

if __name__ == "__main__":
    main()
