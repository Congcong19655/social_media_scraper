"""Utilities for LinkedIn connection management."""

import json
from pathlib import Path
from typing import List, Set, Dict, Any, Optional
from loguru import logger

from .models import Connection


def load_connections_from_file(file_path: Path) -> List[Connection]:
    """
    Load connections from a previously saved JSON file.

    Args:
        file_path: Path to the LinkedIn connections JSON file

    Returns:
        List of Connection objects
    """
    if not file_path.exists():
        logger.warning(f"Connections file not found: {file_path}")
        return []

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        connections_data = data.get("connections", [])
        connections = []

        for conn_data in connections_data:
            try:
                conn = Connection(
                    profile_url=conn_data.get("profile_url"),
                    profile_username=conn_data.get("profile_username")
                )
                connections.append(conn)
            except Exception as e:
                logger.warning(f"Could not parse connection: {e}")
                continue

        logger.info(f"Loaded {len(connections)} connections from {file_path}")
        return connections

    except Exception as e:
        logger.error(f"Failed to load connections from {file_path}: {e}")
        return []


def find_new_connections(
    new_connections: List[Connection],
    existing_connections: List[Connection]
) -> List[Connection]:
    """
    Find connections that are in new_connections but not in existing_connections.

    Args:
        new_connections: List of newly scraped connections
        existing_connections: List of previously saved connections

    Returns:
        List of Connection objects that are new
    """
    # Create sets of profile URLs for quick lookup
    existing_urls: Set[str] = set()
    existing_usernames: Set[str] = set()

    for conn in existing_connections:
        if conn.profile_url:
            existing_urls.add(conn.profile_url)
        if conn.profile_username:
            existing_usernames.add(conn.profile_username)

    # Find new connections
    new_conn_list: List[Connection] = []

    for conn in new_connections:
        is_new = True

        # Check by URL first
        if conn.profile_url and conn.profile_url in existing_urls:
            is_new = False

        # Also check by username as fallback
        if is_new and conn.profile_username and conn.profile_username in existing_usernames:
            is_new = False

        if is_new:
            new_conn_list.append(conn)

    logger.info(f"Found {len(new_conn_list)} new connections out of {len(new_connections)} total")
    return new_conn_list


def save_new_connections(
    new_connections: List[Connection],
    output_dir: Path,
    scraped_at: Optional[str] = None
) -> Path:
    """
    Save new connections to a separate JSON file.

    Args:
        new_connections: List of new Connection objects
        output_dir: Directory to save the file
        scraped_at: ISO timestamp for when the scrape happened

    Returns:
        Path to the saved file
    """
    from datetime import datetime

    if scraped_at is None:
        scraped_at = datetime.now().isoformat()

    output_dir.mkdir(parents=True, exist_ok=True)

    # Create filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"new_connections_{timestamp}.json"

    # Convert connections to dicts
    connections_data = []
    for conn in new_connections:
        connections_data.append({
            "profile_url": conn.profile_url,
            "profile_username": conn.profile_username
        })

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "scraped_at": scraped_at,
            "new_connections_count": len(new_connections),
            "new_connections": connections_data
        }, f, ensure_ascii=False, indent=2)

    logger.info(f"Saved {len(new_connections)} new connections to {output_file}")
    return output_file
