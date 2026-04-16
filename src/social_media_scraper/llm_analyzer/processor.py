"""
Process 3-agent pipeline outputs and save as markdown, JSON, and CSV.
"""
import json
import os
import csv
from pathlib import Path
from datetime import datetime
from typing import Optional
from loguru import logger

from .reader import AggregatedContent
from .agents import ProfileSummary, StructuredFlags, SellingPoints, SellingPoint


class LeadProcessor:
    """Process and save 3-agent pipeline results."""

    # Column order for structured data CSV
    CSV_COLUMNS = [
        "name",
        "recent_travel",
        "recent_marriage",
        "recent_child_birth",
        "new_job",
        "new_home",
        "car_purchase",
        "health_issue",
        "hobby_sports",
        "family_activities",
        "retirement_planning",
        "business_owner",
        "property_investment",
        "education_planning",
        "processed_at",
    ]

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def process_and_save(
        self,
        account_name: str,
        aggregated: AggregatedContent,
        profile_summary: Optional[ProfileSummary],
        structured_flags: Optional[StructuredFlags],
        selling_points: Optional[SellingPoints],
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        save_json: bool = True,
    ) -> Path:
        """
        Process and save all three agent outputs.
        Returns the path to the markdown file.
        """
        # Generate markdown
        markdown = self._generate_markdown(
            account_name=account_name,
            aggregated=aggregated,
            profile_summary=profile_summary,
            structured_flags=structured_flags,
            selling_points=selling_points,
            from_date=from_date,
            to_date=to_date,
        )

        # Save markdown
        md_path = self.output_dir / f"{account_name}.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(markdown)

        # Save JSON if requested
        if save_json:
            json_path = self.output_dir / f"{account_name}.json"
            json_data = {
                "account_name": account_name,
                "generated_at": datetime.now().isoformat(),
                "from_date": from_date,
                "to_date": to_date,
                "sources": {
                    "instagram": aggregated.has_instagram,
                    "xiaohongshu": aggregated.has_xiaohongshu,
                    "linkedin": aggregated.has_linkedin,
                },
                "total_items": len(aggregated.items),
                "profile_summary": profile_summary.model_dump() if profile_summary else None,
                "structured_flags": structured_flags.model_dump() if structured_flags else None,
                "selling_points": selling_points.model_dump() if selling_points else None,
            }
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(json_data, f, indent=2, ensure_ascii=False)

        # Append structured flags to combined CSV
        if structured_flags:
            self._append_to_csv(structured_flags)

        logger.info(f"Saved 3-agent analysis for {account_name} to {md_path}")
        return md_path

    def _generate_markdown(
        self,
        account_name: str,
        aggregated: AggregatedContent,
        profile_summary: Optional[ProfileSummary],
        structured_flags: Optional[StructuredFlags],
        selling_points: Optional[SellingPoints],
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> str:
        """Generate comprehensive markdown output from all three agents."""
        lines = []

        # Header
        lines.append(f"# Insurance Lead Analysis: {account_name}")
        lines.append("")
        lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        date_range_str = f"{from_date or 'any'} to {to_date or 'any'}"
        lines.append(f"Date range: {date_range_str}")

        sources = []
        if aggregated.has_instagram:
            sources.append("Instagram")
        if aggregated.has_xiaohongshu:
            sources.append("Xiaohongshu")
        if aggregated.has_linkedin:
            sources.append("LinkedIn")
        lines.append(f"Sources: {', '.join(sources)}")
        lines.append("")

        # Section 1: Profile Summary (Agent 1)
        lines.append("---")
        lines.append("")
        lines.append("## Profile Summary")
        lines.append("")
        if profile_summary:
            lines.append(profile_summary.profile_summary.strip())
            lines.append("")
            lines.append("### Key Insights")
            lines.append("")
            for insight in profile_summary.key_insights:
                lines.append(f"- {insight}")
        else:
            lines.append("*Profile summary not available.*")
        lines.append("")

        # Section 2: Structured Indicators (Agent 2)
        lines.append("---")
        lines.append("")
        lines.append("## Propensity Indicators")
        lines.append("")
        if structured_flags:
            lines.append("| Indicator | Status |")
            lines.append("|-----------|--------|")

            # Map field names to readable labels
            field_labels = {
                "recent_travel": "Recent Travel",
                "recent_marriage": "Recent Marriage/Engagement",
                "recent_child_birth": "New Child/Pregnancy",
                "new_job": "New Job/Promotion",
                "new_home": "New Home/Move",
                "car_purchase": "Car Purchase",
                "health_issue": "Health Focus/Issues",
                "hobby_sports": "Sports/Hobbies",
                "family_activities": "Family-Focused",
                "retirement_planning": "Retirement Planning",
                "business_owner": "Business Owner",
                "property_investment": "Property Investment",
                "education_planning": "Education Planning",
            }

            flags_dict = structured_flags.model_dump()
            for field, label in field_labels.items():
                value = flags_dict.get(field, 0)
                status = "✓ Yes" if value == 1 else "✗ No"
                lines.append(f"| {label} | {status} |")
        else:
            lines.append("*Structured indicators not available.*")
        lines.append("")

        # Section 3: Selling Points (Agent 3)
        lines.append("---")
        lines.append("")
        lines.append("## Recommended Selling Points")
        lines.append("")

        if selling_points and selling_points.selling_points:
            for i, point in enumerate(selling_points.selling_points, 1):
                lines.append(f"### Point {i}")
                lines.append("")
                lines.append(point.point_text.strip())
                lines.append("")
                lines.append(f"**Source**: {point.reference_post}")
                lines.append("")
                lines.append(f"> {point.reference_snippet.strip()}")
                lines.append("")
                lines.append(f"**Why this matters**: {point.reasoning.strip()}")
                lines.append("")
                lines.append("---")
                lines.append("")
        else:
            lines.append("*No specific selling points generated.*")
            lines.append("")

        return "\n".join(lines)

    def _append_to_csv(self, structured_flags: StructuredFlags) -> None:
        """Append structured flags to the combined CSV file."""
        csv_path = self.output_dir / "structured_data.csv"
        file_exists = csv_path.exists()

        # Prepare row data
        row_data = structured_flags.model_dump()
        row_data["processed_at"] = datetime.now().isoformat()

        # Ensure all columns exist
        for col in self.CSV_COLUMNS:
            if col not in row_data:
                row_data[col] = ""

        try:
            # Write or append to CSV
            mode = "a" if file_exists else "w"
            with open(csv_path, mode, encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self.CSV_COLUMNS)
                if not file_exists:
                    writer.writeheader()
                writer.writerow(row_data)
            logger.debug(f"Updated structured data CSV: {csv_path}")
        except Exception as e:
            logger.error(f"Failed to write to structured data CSV: {e}", exc_info=True)
