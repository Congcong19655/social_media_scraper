"""Utilities to export new leads to CSV format."""

import csv
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from loguru import logger


@dataclass
class LeadEntry:
    """Represents a single lead entry for CSV export."""
    name: str = ""
    instagram: str = ""
    xiaohongshu: str = ""
    linkedin: str = ""


def load_new_leads_from_file(file_path: Path) -> List[LeadEntry]:
    """
    Load new leads from a JSON file and convert to LeadEntry objects.

    Args:
        file_path: Path to the new leads JSON file

    Returns:
        List of LeadEntry objects
    """
    if not file_path.exists():
        logger.warning(f"Leads file not found: {file_path}")
        return []

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        leads: List[LeadEntry] = []

        # Determine what type of leads file this is
        if "new_connections" in data:
            # LinkedIn connections
            for conn in data["new_connections"]:
                username = conn.get("profile_username", "")
                lead = LeadEntry(
                    name=username,
                    linkedin=username
                )
                leads.append(lead)
            logger.info(f"Loaded {len(leads)} LinkedIn connections from {file_path}")

        elif "new_followers" in data:
            # Instagram followers
            for user in data["new_followers"]:
                username = user.get("username", "")
                lead = LeadEntry(
                    name=username,
                    instagram=username
                )
                leads.append(lead)
            logger.info(f"Loaded {len(leads)} Instagram followers from {file_path}")

        elif "new_following" in data:
            # Instagram following
            for user in data["new_following"]:
                username = user.get("username", "")
                lead = LeadEntry(
                    name=username,
                    instagram=username
                )
                leads.append(lead)
            logger.info(f"Loaded {len(leads)} Instagram following from {file_path}")

        else:
            logger.warning(f"Unrecognized leads file format: {file_path}")

        return leads

    except Exception as e:
        logger.error(f"Failed to load leads from {file_path}: {e}")
        return []


def merge_leads(existing_leads: List[LeadEntry], new_leads: List[LeadEntry]) -> List[LeadEntry]:
    """
    Merge new leads into existing leads, avoiding duplicates.
    If a duplicate is found, keep the existing name (don't overwrite with username).

    Args:
        existing_leads: List of existing LeadEntry objects
        new_leads: List of new LeadEntry objects to merge

    Returns:
        Merged list of LeadEntry objects
    """
    merged = existing_leads.copy()

    for new_lead in new_leads:
        # Check if this lead already exists
        found = False
        existing_match = None

        # Check by Instagram
        if new_lead.instagram:
            for existing in existing_leads:
                if existing.instagram == new_lead.instagram:
                    found = True
                    existing_match = existing
                    break

        # Check by LinkedIn
        if not found and new_lead.linkedin:
            for existing in existing_leads:
                if existing.linkedin == new_lead.linkedin:
                    found = True
                    existing_match = existing
                    break

        # Check by Xiaohongshu
        if not found and new_lead.xiaohongshu:
            for existing in existing_leads:
                if existing.xiaohongshu == new_lead.xiaohongshu:
                    found = True
                    existing_match = existing
                    break

        if not found:
            merged.append(new_lead)
        else:
            # If existing doesn't have a name but new one does, update it
            if existing_match and not existing_match.name and new_lead.name:
                existing_match.name = new_lead.name
            # If existing doesn't have a platform but new one does, add it
            if existing_match:
                if not existing_match.instagram and new_lead.instagram:
                    existing_match.instagram = new_lead.instagram
                if not existing_match.linkedin and new_lead.linkedin:
                    existing_match.linkedin = new_lead.linkedin
                if not existing_match.xiaohongshu and new_lead.xiaohongshu:
                    existing_match.xiaohongshu = new_lead.xiaohongshu

    logger.info(f"Merged leads: {len(existing_leads)} existing + {len(new_leads)} new = {len(merged)} total")
    return merged


def load_existing_csv(csv_path: Path) -> List[LeadEntry]:
    """
    Load existing leads from a CSV file.

    Args:
        csv_path: Path to the CSV file

    Returns:
        List of LeadEntry objects
    """
    if not csv_path.exists():
        logger.info(f"Existing CSV not found at {csv_path}, will create new")
        return []

    leads: List[LeadEntry] = []

    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                lead = LeadEntry(
                    name=row.get("name", ""),
                    instagram=row.get("instagram", ""),
                    xiaohongshu=row.get("xiaohongshu", ""),
                    linkedin=row.get("linkedin", "")
                )
                leads.append(lead)

        logger.info(f"Loaded {len(leads)} existing leads from {csv_path}")
        return leads

    except Exception as e:
        logger.error(f"Failed to load existing CSV from {csv_path}: {e}")
        return []


def export_leads_to_csv(leads: List[LeadEntry], output_path: Path) -> Path:
    """
    Export leads to a CSV file in the accounts format.

    Args:
        leads: List of LeadEntry objects to export
        output_path: Path to save the CSV file

    Returns:
        Path to the saved CSV file
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = ["name", "instagram", "xiaohongshu", "linkedin"]

    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for lead in leads:
            writer.writerow({
                "name": lead.name,
                "instagram": lead.instagram,
                "xiaohongshu": lead.xiaohongshu,
                "linkedin": lead.linkedin
            })

    logger.info(f"Exported {len(leads)} leads to {output_path}")
    return output_path


def convert_leads_to_csv(
    leads_file: Path,
    existing_csv: Optional[Path] = None,
    output_csv: Optional[Path] = None
) -> Path:
    """
    Convert a new leads JSON file to CSV format, merging with existing CSV if provided.

    Args:
        leads_file: Path to the new leads JSON file
        existing_csv: Optional path to existing CSV file to merge with
        output_csv: Optional path for output CSV (defaults to leads_file with .csv extension)

    Returns:
        Path to the saved CSV file
    """
    # Load new leads
    new_leads = load_new_leads_from_file(leads_file)
    if not new_leads:
        logger.warning("No leads to convert")
        return None

    # Determine output path
    if output_csv is None:
        output_csv = leads_file.with_suffix(".csv")

    # Load existing leads if provided
    existing_leads = []
    if existing_csv and existing_csv.exists():
        existing_leads = load_existing_csv(existing_csv)

    # Merge leads
    merged_leads = merge_leads(existing_leads, new_leads)

    # Export
    return export_leads_to_csv(merged_leads, output_csv)


def merge_all_leads_to_accounts_csv(
    new_leads_dir: Path,
    accounts_csv: Path,
) -> Path:
    """
    Load all JSON files from new_leads directory, merge with existing accounts CSV,
    and save the merged result back to accounts CSV.

    Args:
        new_leads_dir: Directory containing new leads JSON files
        accounts_csv: Path to the accounts CSV file to update

    Returns:
        Path to the updated accounts CSV file
    """
    if not new_leads_dir.exists():
        logger.warning(f"New leads directory not found: {new_leads_dir}")
        return None

    # Load existing accounts
    all_leads = load_existing_csv(accounts_csv)

    # Find all JSON files in new_leads directory
    json_files = list(new_leads_dir.glob("*.json"))

    if not json_files:
        logger.warning(f"No JSON files found in {new_leads_dir}")
        if all_leads:
            # Just re-export the existing ones
            return export_leads_to_csv(all_leads, accounts_csv)
        return None

    logger.info(f"Found {len(json_files)} JSON files in {new_leads_dir}")

    # Load and merge each JSON file
    for json_file in json_files:
        new_leads = load_new_leads_from_file(json_file)
        if new_leads:
            all_leads = merge_leads(all_leads, new_leads)

    # Export merged leads to accounts CSV
    return export_leads_to_csv(all_leads, accounts_csv)
