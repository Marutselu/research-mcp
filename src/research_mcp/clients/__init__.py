"""External API client wrappers."""

from research_mcp.clients.http import (
    APIError,
    AuthenticationError,
    NotFoundError,
    RateLimitError,
)

__all__ = [
    "APIError",
    "AuthenticationError",
    "NotFoundError",
    "RateLimitError",
]
