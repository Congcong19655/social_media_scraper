"""
Doubao LLM client for lead extraction.
Uses OpenAI-compatible API to call Doubao-Seed-2.0-lite.
"""
import json
import base64
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel
from openai import OpenAI
from loguru import logger

from .reader import AggregatedContent, ContentItem


class ExtractedLead(BaseModel):
    """A single extracted lead (life event or insurance opportunity)."""
    opportunity_type: str
    date: Optional[str] = None
    description: str
    confidence_score: float
    insurance_recommendation: str
    source_snippet: str


class LeadExtractionResponse(BaseModel):
    """Response from LLM."""
    leads: List[ExtractedLead]
    summary: Optional[str] = None


class DoubaoLeadClient:
    """Client for Doubao LLM to extract insurance leads."""

    SYSTEM_PROMPT = """You are an expert insurance sales lead analyst.
Read through the social media posts, images, and profile information and identify ANY insurance sales opportunities.

Look for:
1. Major life events (marriage, new child, new job, new home, car purchase, retirement, etc.)
2. Lifestyle indicators (hobbies, travel, sports, family activities that suggest insurance needs)
3. Professional changes (career advancements, business ownership)
4. Health and wellness mentions
5. Property and asset acquisitions
6. Family changes and milestones
7. Any other content that suggests a need for insurance (life, health, auto, home, travel, business, etc.)

For each opportunity you find, identify:
- opportunity_type: Category like: life_event, lifestyle_indicator, professional_change, health_related, property_asset, family_milestone, general_opportunity, or other
- date: The date if mentioned or can be inferred (format YYYY-MM or YYYY-MM-DD)
- description: A clear description of the opportunity
- confidence_score: How confident you are this is a real opportunity (0.0 to 1.0)
- insurance_recommendation: What type(s) of insurance would be relevant and why
- source_snippet: The original text snippet that led to this conclusion

Also provide a brief "summary" field with an overall sales strategy recommendation for this person.

Output ONLY valid JSON with:
- top-level `leads` array containing the opportunities
- top-level `summary` string with your overall assessment and strategy

If no opportunities found, output `{ "leads": [], "summary": "No immediate insurance opportunities identified." }`.
"""

    def __init__(
        self,
        api_key: str,
        endpoint: str,
        model: str = "doubao-seed-2-0-lite-260215",
    ):
        self.client = OpenAI(
            api_key=api_key,
            base_url=endpoint,
        )
        self.model = model

    def extract_leads(self, content: AggregatedContent) -> tuple[List[ExtractedLead], Optional[str]]:
        """Extract leads from aggregated content."""
        # Build the multimodal message
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
        ]

        user_content = []

        # Add all content items sorted chronologically
        # Limit total content blocks to avoid exceeding context window
        max_content_blocks = 150
        max_images_total = 50
        content_blocks_added = 0
        images_added = 0

        for item in content.items:
            if content_blocks_added >= max_content_blocks:
                break

            # Add text content
            if item.text.strip():
                # Truncate very long texts to save context space
                text = item.text
                if len(text) > 1500:
                    text = text[:1500] + "\n... (truncated)"
                user_content.append({
                    "type": "text",
                    "text": f"\n--- {item.platform} {item.content_type} ---\n{text}\n",
                })
                content_blocks_added += 1

            # Add locally downloaded images (encoded as base64)
            # External URLs can't be accessed by Doubao due to CORS/hotlinking blocks
            if images_added >= max_images_total:
                continue

            # Add local images
            for local_path in item.local_image_paths[:3]:  # Limit to 3 images per item
                if images_added >= max_images_total:
                    break
                try:
                    # Read and encode image as base64
                    with open(local_path, "rb") as f:
                        image_bytes = f.read()
                    base64_image = base64.b64encode(image_bytes).decode("utf-8")
                    # Guess mime type based on extension
                    ext = Path(local_path).suffix.lower()
                    if ext in [".jpg", ".jpeg"]:
                        mime = "image/jpeg"
                    elif ext == ".png":
                        mime = "image/png"
                    else:
                        mime = "image/jpeg"
                    data_url = f"data:{mime};base64,{base64_image}"
                    user_content.append({
                        "type": "image_url",
                        "image_url": {"url": data_url},
                    })
                    images_added += 1
                    content_blocks_added += 1
                except Exception as e:
                    logger.warning(f"Failed to read local image {local_path}: {e}")
                    continue

        messages.append({"role": "user", "content": user_content})

        logger.info(f"Calling Doubao LLM with {len(user_content)} content blocks ({images_added} images) for {content.account_name}")

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.0,
            )

            response_text = response.choices[0].message.content
            if not response_text:
                logger.warning(f"Empty response from Doubao for {content.account_name}")
                return [], None

            # Try to extract JSON - robust to extra text before/after
            def extract_json(text: str) -> Optional[dict]:
                """Extract JSON from text, handling extra content before/after."""
                # Try direct parse first
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    pass

                # Try to find JSON by looking for first { and last }
                try:
                    start_idx = text.find('{')
                    end_idx = text.rfind('}')
                    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                        json_str = text[start_idx:end_idx+1]
                        return json.loads(json_str)
                except json.JSONDecodeError:
                    pass

                return None

            # Parse JSON response with robust extraction
            parsed = extract_json(response_text)
            if not parsed or not isinstance(parsed, dict):
                logger.warning(f"Could not parse valid JSON from Doubao for {content.account_name}. Response: {response_text[:200]}...")
                return [], None

            leads_data = parsed.get("leads", [])
            if not isinstance(leads_data, list):
                leads_data = []

            # Validate with Pydantic - handle both old and new field names
            leads = []
            for lead_data in leads_data:
                try:
                    # Map old field names to new ones for backward compatibility
                    normalized_data = lead_data.copy() if isinstance(lead_data, dict) else {}
                    if "event_type" in normalized_data and "opportunity_type" not in normalized_data:
                        normalized_data["opportunity_type"] = normalized_data.pop("event_type")
                    if "insurance_need" in normalized_data and "insurance_recommendation" not in normalized_data:
                        normalized_data["insurance_recommendation"] = normalized_data.pop("insurance_need")

                    lead = ExtractedLead(**normalized_data)
                    leads.append(lead)
                except Exception as e:
                    logger.warning(f"Invalid lead format from LLM: {e}, data={lead_data}")

            summary = parsed.get("summary")
            if summary:
                logger.info(f"Summary for {content.account_name}: {summary}")

            logger.info(f"Extracted {len(leads)} leads for {content.account_name}")
            return leads, summary

        except Exception as e:
            import openai
            if isinstance(e, openai.APIStatusError):
                # Use logging that doesn't conflict with curly braces in JSON
                err_text = e.response.text if hasattr(e, 'response') and e.response else str(e)
                logger.error(f"Failed to call Doubao API for {content.account_name}: " + str(err_text), exc_info=True)
            elif isinstance(e, openai.APIError):
                logger.error(f"Failed to call Doubao API for {content.account_name}: " + str(e.message if hasattr(e, 'message') else e), exc_info=True)
            else:
                logger.error(f"Failed to call Doubao API for {content.account_name}: {repr(e)}", exc_info=True)
            return [], None
