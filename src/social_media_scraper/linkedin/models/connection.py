"""Pydantic models for LinkedIn Connection data."""

from typing import Optional
from pydantic import BaseModel, HttpUrl, field_validator, model_validator


class Connection(BaseModel):
    """
    LinkedIn Connection model with validation.

    Represents a connection from the LinkedIn connections list.
    """

    profile_url: str
    profile_username: Optional[str] = None

    @field_validator("profile_url")
    @classmethod
    def validate_profile_url(cls, v: str) -> str:
        """Validate that URL is a LinkedIn profile URL."""
        if "linkedin.com/in/" not in v:
            raise ValueError("Must be a valid LinkedIn profile URL (contains /in/)")
        return v

    @model_validator(mode="after")
    def extract_username(self) -> "Connection":
        """Extract username from profile_url if not provided."""
        if self.profile_username is None and self.profile_url:
            url = self.profile_url
            # Extract username from URL like https://www.linkedin.com/in/username/
            # or https://www.linkedin.com/in/username/en
            if "/in/" in url:
                parts = url.split("/in/")
                if len(parts) > 1:
                    username_part = parts[1].rstrip("/")
                    # Remove any language suffix like /en, /zh, etc.
                    lang_suffixes = ["/en", "/zh", "/es", "/fr", "/de", "/ja", "/ko"]
                    for suffix in lang_suffixes:
                        if username_part.endswith(suffix):
                            username_part = username_part[:-len(suffix)]
                        elif suffix + "/" in username_part:
                            username_part = username_part.replace(suffix + "/", "/")
                    # Remove any query parameters
                    username_part = username_part.split("?")[0]
                    # Remove any trailing slashes
                    username_part = username_part.rstrip("/")
                    self.profile_username = username_part
        return self

    def to_dict(self) -> dict:
        """
        Convert to dictionary.

        Returns:
            Dictionary representation of the connection
        """
        return self.model_dump()

    def to_json(self, **kwargs) -> str:
        """
        Convert to JSON string.

        Args:
            **kwargs: Additional arguments for model_dump_json (e.g., indent=2)

        Returns:
            JSON string representation
        """
        return self.model_dump_json(**kwargs)

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"<Connection {self.name}\n"
            f"  Company: {self.company}\n"
            f"  Title: {self.title}\n"
            f"  Location: {self.location}\n"
            f"  Username: {self.profile_username}>"
        )
