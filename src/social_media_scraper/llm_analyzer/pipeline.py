"""
Three-agent pipeline orchestrator for insurance lead generation.

Runs:
1. ProfileSummaryAgent and StructuredDataAgent in parallel
2. SellingPointsAgent (depends on ProfileSummaryAgent output)
"""
import concurrent.futures
from typing import Optional, Tuple
from loguru import logger

from .reader import AggregatedContent
from .agents import (
    ProfileSummaryAgent,
    StructuredDataAgent,
    SellingPointsAgent,
    ProfileSummary,
    StructuredFlags,
    SellingPoints,
)


class ThreeAgentPipeline:
    """
    Orchestrates the three-agent pipeline:
    - Agents 1 and 2 run in parallel
    - Agent 3 runs after Agent 1 completes
    """

    def __init__(
        self,
        api_key: str,
        endpoint: str,
        model: str = "doubao-seed-2-0-lite-260215",
        max_workers: int = 2,
    ):
        self.api_key = api_key
        self.endpoint = endpoint
        self.model = model
        self.max_workers = max_workers

        # Initialize agents
        self.profile_agent = ProfileSummaryAgent(api_key, endpoint, model)
        self.flags_agent = StructuredDataAgent(api_key, endpoint, model)
        self.selling_points_agent = SellingPointsAgent(api_key, endpoint, model)

    def run(
        self,
        content: AggregatedContent,
    ) -> Tuple[Optional[ProfileSummary], Optional[StructuredFlags], Optional[SellingPoints]]:
        """
        Run the full three-agent pipeline.

        Returns:
            Tuple of (profile_summary, structured_flags, selling_points)
        """
        account_name = content.account_name
        logger.info(f"Starting 3-agent pipeline for {account_name}")

        # Step 1: Run Agent 1 (Profile Summary) and Agent 2 (Structured Flags) in parallel
        logger.info(f"Running Agent 1 (Profile Summary) and Agent 2 (Structured Data) in parallel for {account_name}")

        profile_summary: Optional[ProfileSummary] = None
        structured_flags: Optional[StructuredFlags] = None

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit both tasks
            future_profile = executor.submit(self.profile_agent.generate_summary, content)
            future_flags = executor.submit(self.flags_agent.generate_flags, content)

            # Get results
            try:
                profile_summary = future_profile.result()
                if profile_summary:
                    logger.info(f"Agent 1 (Profile Summary) completed for {account_name}")
                else:
                    logger.warning(f"Agent 1 (Profile Summary) returned no result for {account_name}")
            except Exception as e:
                logger.error(f"Agent 1 (Profile Summary) failed for {account_name}: {e}", exc_info=True)

            try:
                structured_flags = future_flags.result()
                if structured_flags:
                    logger.info(f"Agent 2 (Structured Data) completed for {account_name}")
                else:
                    logger.warning(f"Agent 2 (Structured Data) returned no result for {account_name}")
            except Exception as e:
                logger.error(f"Agent 2 (Structured Data) failed for {account_name}: {e}", exc_info=True)

        # Step 2: Run Agent 3 (Selling Points) with output from Agent 1
        selling_points: Optional[SellingPoints] = None

        if profile_summary:
            logger.info(f"Running Agent 3 (Selling Points) for {account_name}")
            try:
                selling_points = self.selling_points_agent.generate_selling_points(content, profile_summary)
                if selling_points:
                    logger.info(f"Agent 3 (Selling Points) completed for {account_name}: {len(selling_points.selling_points)} points")
                else:
                    logger.warning(f"Agent 3 (Selling Points) returned no result for {account_name}")
            except Exception as e:
                logger.error(f"Agent 3 (Selling Points) failed for {account_name}: {e}", exc_info=True)
        else:
            logger.warning(f"Skipping Agent 3 (Selling Points) because Agent 1 failed for {account_name}")

        logger.info(f"3-agent pipeline completed for {account_name}")
        return profile_summary, structured_flags, selling_points
