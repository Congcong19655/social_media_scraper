"""
Shared LLM utilities and base client for Doubao API.
Uses OpenAI-compatible API to call Doubao-Seed-2.0-lite.
"""
import json
import base64
from pathlib import Path
from typing import List, Optional, Dict, Any
from openai import OpenAI
from loguru import logger

from .reader import AggregatedContent, ContentItem


def extract_json(text: str) -> Optional[dict]:
    """
    Extract JSON from text, handling extra content before/after.
    Robust to markdown code blocks, extra text, etc.
    """
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

    # Try to extract from markdown code blocks
    try:
        # Look for ```json ... ```
        import re
        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if match:
            return json.loads(match.group(1))
    except json.JSONDecodeError:
        pass

    return None


def build_multimodal_message(
    content: AggregatedContent,
    max_content_blocks: int = 150,
    max_images_total: int = 50,
    max_text_length: int = 1500,
) -> List[Dict[str, Any]]:
    """
    Build a multimodal message content with text + base64 images.
    Returns a list suitable for OpenAI API message content.
    """
    user_content = []
    content_blocks_added = 0
    images_added = 0

    for item_idx, item in enumerate(content.items):
        if content_blocks_added >= max_content_blocks:
            break

        # Add text content
        if item.text.strip():
            # Truncate very long texts to save context space
            text = item.text
            if len(text) > max_text_length:
                text = text[:max_text_length] + "\n... (truncated)"

            # Include item index for reference
            header = f"\n--- [{item_idx}] {item.platform} {item.content_type} ---\n"
            user_content.append({
                "type": "text",
                "text": header + text,
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

                # Add image with reference to which item it came from
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": data_url},
                })
                images_added += 1
                content_blocks_added += 1
            except Exception as e:
                logger.warning(f"Failed to read local image {local_path}: {e}")
                continue

    return user_content


class BaseDoubaoClient:
    """Base class for Doubao LLM clients with common setup."""

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

    def _call_llm(
        self,
        system_prompt: str,
        user_content: List[Dict[str, Any]],
        account_name: str,
        temperature: float = 0.0,
    ) -> Optional[str]:
        """
        Call the Doubao LLM with the given prompts.
        Returns the response text or None on error.
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        logger.info(f"Calling Doubao LLM with {len(user_content)} content blocks for {account_name}")

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
            )

            response_text = response.choices[0].message.content
            if not response_text:
                logger.warning(f"Empty response from Doubao for {account_name}")
                return None

            return response_text

        except Exception as e:
            import openai
            if isinstance(e, openai.APIStatusError):
                err_text = e.response.text if hasattr(e, 'response') and e.response else str(e)
                logger.error(f"Failed to call Doubao API for {account_name}: " + str(err_text), exc_info=True)
            elif isinstance(e, openai.APIError):
                logger.error(f"Failed to call Doubao API for {account_name}: " + str(e.message if hasattr(e, 'message') else e), exc_info=True)
            else:
                logger.error(f"Failed to call Doubao API for {account_name}: {repr(e)}", exc_info=True)
            return None
