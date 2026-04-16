"""
Process extracted leads and output as markdown (primary) and JSON (optional).
"""
import json
import os
from pathlib import Path
from datetime import datetime
from typing import List, Optional
from loguru import logger

from .reader import AggregatedContent
from .llm import ExtractedLead


class LeadProcessor:
    """Process and save lead extraction results."""

    OPPORTUNITY_TYPE_NAMES = {
        # Old event types for backward compatibility
        "marriage": "Marriage",
        "new_child": "New Child",
        "engagement": "Engagement",
        "new_job": "New Job",
        "new_home": "New Home Purchase",
        "car_purchase": "Car Purchase",
        "moving": "Moving",
        "retirement": "Retirement",
        "major_purchase": "Major Purchase",
        "health_change": "Health Change",
        "family_change": "Family Change",
        # New opportunity types
        "life_event": "Life Event",
        "lifestyle_indicator": "Lifestyle Indicator",
        "professional_change": "Professional Change",
        "health_related": "Health Related",
        "property_asset": "Property/Asset",
        "family_milestone": "Family Milestone",
        "general_opportunity": "General Opportunity",
        "other": "Other Opportunity",
    }

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def process_and_save(
        self,
        account_name: str,
        aggregated: AggregatedContent,
        leads: List[ExtractedLead],
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        save_json: bool = True,
        summary: Optional[str] = None,
    ) -> Path:
        """
        Process leads and save as markdown (primary output) and optionally JSON.
        Returns the path to the markdown file.
        """
        # Generate markdown
        markdown = self._generate_markdown(
            account_name=account_name,
            aggregated=aggregated,
            leads=leads,
            from_date=from_date,
            to_date=to_date,
            summary=summary,
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
                "total_leads": len(leads),
                "summary": summary,
                "leads": [lead.model_dump() for lead in leads],
            }
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(json_data, f, indent=2, ensure_ascii=False)

        logger.info(f"Saved lead analysis for {account_name} to {md_path}")
        return md_path

    def _generate_markdown(
        self,
        account_name: str,
        aggregated: AggregatedContent,
        leads: List[ExtractedLead],
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> str:
        """Generate markdown output from extracted leads."""
        lines = []

        # Header
        lines.append(f"# Lead Analysis: {account_name}")
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

        # LLM Summary if available
        if summary:
            lines.append("## Overall Strategy Summary")
            lines.append("")
            lines.append(summary.strip())
            lines.append("")
            lines.append("---")
            lines.append("")

        # Summary
        lines.append("## Opportunities Found")
        lines.append("")
        lines.append(f"Total insurance opportunities identified: **{len(leads)}**")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Individual opportunities
        for i, lead in enumerate(leads, 1):
            # Handle both old and new field names
            opp_type = getattr(lead, 'opportunity_type', None) or getattr(lead, 'event_type', 'other')
            opp_name = self.OPPORTUNITY_TYPE_NAMES.get(opp_type, opp_type)
            lines.append(f"## Opportunity {i}: {opp_name}")
            lines.append("")

            if lead.date:
                lines.append(f"**Date**: {lead.date}")
            else:
                lines.append(f"**Date**: Not specified")

            confidence_pct = int(round(lead.confidence_score * 100))
            lines.append(f"**Confidence**: {confidence_pct}%")

            lines.append(f"**Description**: {lead.description.strip()}")

            # Handle both old and new field names
            insurance_rec = getattr(lead, 'insurance_recommendation', None) or getattr(lead, 'insurance_need', '')
            lines.append(f"**Insurance Recommendation**: {insurance_rec.strip()}")
            lines.append(f"**Source**: `{lead.source_snippet.strip()}`")
            lines.append("")
            lines.append("---")
            lines.append("")

        if not leads:
            lines.append("## No insurance opportunities identified")
            lines.append("")
            if not summary:
                lines.append("Continue monitoring this account for future insurance needs.")
                lines.append("")

        return "\n".join(lines)
