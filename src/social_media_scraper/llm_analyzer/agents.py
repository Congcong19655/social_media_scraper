"""
Three specialized LLM agents for insurance lead generation.

1. ProfileSummaryAgent: Generates sales-focused profile summary
2. StructuredDataAgent: Outputs binary flags for ML propensity modeling
3. SellingPointsAgent: Generates specific selling points with references
"""
from typing import List, Optional
from pydantic import BaseModel
from loguru import logger

from .reader import AggregatedContent
from .llm import BaseDoubaoClient, build_multimodal_message, extract_json


# ============================================================================
# Pydantic Models for Agent Outputs
# ============================================================================

class ProfileSummary(BaseModel):
    """Output from Agent 1: Sales-focused profile summary."""
    profile_summary: str  # 2-3 paragraph narrative
    key_insights: List[str]  # Bullet points of key sales insights


class StructuredFlags(BaseModel):
    """Output from Agent 2: Binary flags for ML propensity modeling."""
    name: str
    recent_travel: int = 0
    recent_marriage: int = 0
    recent_child_birth: int = 0
    new_job: int = 0
    new_home: int = 0
    car_purchase: int = 0
    health_issue: int = 0
    hobby_sports: int = 0
    family_activities: int = 0
    retirement_planning: int = 0
    business_owner: int = 0
    property_investment: int = 0
    education_planning: int = 0


class SellingPoint(BaseModel):
    """Individual selling point with source reference."""
    point_text: str  # The specific selling point/insurance recommendation
    reference_post: str  # Format: "[{index}] {platform} {content_type}"
    reference_snippet: str  # Exact text snippet from the source
    reasoning: str  # Why this selling point is relevant


class SellingPoints(BaseModel):
    """Output from Agent 3: List of selling points."""
    selling_points: List[SellingPoint]


# ============================================================================
# Agent 1: Profile Summary Agent
# ============================================================================

class ProfileSummaryAgent(BaseDoubaoClient):
    """Agent that generates a sales-focused profile summary."""

    SYSTEM_PROMPT = """You are an expert insurance sales strategist.
Read through all the social media posts, images, and profile information carefully.

Your task is to synthesize this information into a comprehensive, sales-focused profile summary.

First, output "profile_summary":
- Write 2-3 paragraphs that tell a coherent story about this person
- Focus on their lifestyle, major life events, family situation, professional status, hobbies, and interests
- Highlight aspects that are most relevant to insurance sales opportunities
- Make it narrative and readable, not just a list of facts

Then, output "key_insights" as a list of bullet points:
- 5-10 specific, actionable insights for an insurance salesperson
- Each insight should highlight a specific sales opportunity or important fact to know
- Be specific about what insurance products might be relevant

Output ONLY valid JSON in this format:
{
    "profile_summary": "2-3 paragraph narrative here...",
    "key_insights": [
        "First insight...",
        "Second insight...",
        "..."
    ]
}
"""

    def generate_summary(self, content: AggregatedContent) -> Optional[ProfileSummary]:
        """Generate sales-focused profile summary from aggregated content."""
        user_content = build_multimodal_message(content)
        response_text = self._call_llm(
            system_prompt=self.SYSTEM_PROMPT,
            user_content=user_content,
            account_name=content.account_name,
        )

        if not response_text:
            return None

        parsed = extract_json(response_text)
        if not parsed or not isinstance(parsed, dict):
            logger.warning(f"Could not parse valid JSON for profile summary for {content.account_name}")
            return None

        try:
            return ProfileSummary(**parsed)
        except Exception as e:
            logger.warning(f"Invalid ProfileSummary format: {e}, data={parsed}")
            return None


# ============================================================================
# Agent 2: Structured Data Agent
# ============================================================================

class StructuredDataAgent(BaseDoubaoClient):
    """Agent that outputs binary flags for ML propensity modeling."""

    SYSTEM_PROMPT = """You are a data classifier for insurance propensity modeling.
Read through the social media posts and profile information.

For each of the categories below, output 1 if there is clear evidence the person
has experienced or exhibits this indicator in the last 12-24 months, otherwise 0.

Categories:
- recent_travel: International or frequent domestic travel
- recent_marriage: Got married or engaged
- recent_child_birth: Had a new baby, pregnant, or adopted a child
- new_job: Changed jobs, got promoted, or started a new career
- new_home: Moved, bought a new house, or renovated
- car_purchase: Bought a new or used car
- health_issue: Health concerns, hospital visits, or wellness focus
- hobby_sports: Active in sports, adventure activities, or risky hobbies
- family_activities: Family-focused lifestyle, children's activities
- retirement_planning: Talking about retirement, financial planning for future
- business_owner: Owns a business or is self-employed
- property_investment: Real estate investments, rental properties
- education_planning: Children's education, own education, saving for school

Also include the person's name as "name" (best guess from content).

Output ONLY valid JSON with these fields, all 0 or 1 except name.
Example:
{
    "name": "John Smith",
    "recent_travel": 1,
    "recent_marriage": 0,
    "recent_child_birth": 1,
    "new_job": 0,
    "new_home": 0,
    "car_purchase": 0,
    "health_issue": 0,
    "hobby_sports": 1,
    "family_activities": 1,
    "retirement_planning": 0,
    "business_owner": 0,
    "property_investment": 0,
    "education_planning": 1
}
"""

    def generate_flags(self, content: AggregatedContent) -> Optional[StructuredFlags]:
        """Generate binary flags from aggregated content."""
        user_content = build_multimodal_message(content, max_images_total=20)
        response_text = self._call_llm(
            system_prompt=self.SYSTEM_PROMPT,
            user_content=user_content,
            account_name=content.account_name,
        )

        if not response_text:
            return None

        parsed = extract_json(response_text)
        if not parsed or not isinstance(parsed, dict):
            logger.warning(f"Could not parse valid JSON for structured flags for {content.account_name}")
            return None

        # Ensure name is set
        if "name" not in parsed or not parsed["name"]:
            parsed["name"] = content.account_name

        try:
            return StructuredFlags(**parsed)
        except Exception as e:
            logger.warning(f"Invalid StructuredFlags format: {e}, data={parsed}")
            return None


# ============================================================================
# Agent 3: Selling Points Agent
# ============================================================================

class SellingPointsAgent(BaseDoubaoClient):
    """Agent that generates specific selling points with source references."""

    SYSTEM_PROMPT = """You are an expert insurance sales consultant.
Read through the social media posts, images, and the profile summary carefully.

Your task is to generate specific, persuasive selling points for insurance products
tailored to this person. Each selling point must be tied to specific evidence from
their social media content.

For each selling point, include:
- point_text: A specific, actionable insurance recommendation (2-3 sentences)
- reference_post: Which post this came from, format: "[{index}] {platform} {content_type}"
- reference_snippet: The exact text snippet from that post that supports your point
- reasoning: Explain why this is relevant and how the insurance helps

Generate 3-7 selling points. Focus on the most impactful opportunities.
Prioritize selling points that are clearly supported by evidence.

Output ONLY valid JSON in this format:
{
    "selling_points": [
        {
            "point_text": "Based on your frequent international travel, I recommend a comprehensive travel insurance plan that covers medical emergencies, trip cancellations, and lost luggage...",
            "reference_post": "[5] instagram post",
            "reference_snippet": "Just landed in Tokyo! Can't wait for our 2-week adventure around Japan...",
            "reasoning": "International travel exposes you to risks like medical emergencies abroad and trip disruptions. Travel insurance provides peace of mind and financial protection."
        },
        {
            "point_text": "...",
            "reference_post": "...",
            "reference_snippet": "...",
            "reasoning": "..."
        }
    ]
}
"""

    def generate_selling_points(
        self,
        content: AggregatedContent,
        profile_summary: ProfileSummary,
    ) -> Optional[SellingPoints]:
        """Generate selling points from content and profile summary."""
        # Build message with both profile summary and content
        user_content = []

        # Add profile summary first
        user_content.append({
            "type": "text",
            "text": f"=== Profile Summary ===\n{profile_summary.profile_summary}\n\n=== Key Insights ===\n" +
                    "\n".join(f"- {insight}" for insight in profile_summary.key_insights) + "\n\n",
        })

        # Add the actual content
        content_blocks = build_multimodal_message(content)
        user_content.extend(content_blocks)

        response_text = self._call_llm(
            system_prompt=self.SYSTEM_PROMPT,
            user_content=user_content,
            account_name=content.account_name,
        )

        if not response_text:
            return None

        parsed = extract_json(response_text)
        if not parsed or not isinstance(parsed, dict):
            logger.warning(f"Could not parse valid JSON for selling points for {content.account_name}")
            return None

        try:
            return SellingPoints(**parsed)
        except Exception as e:
            logger.warning(f"Invalid SellingPoints format: {e}, data={parsed}")
            return None
