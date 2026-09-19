"""V1 public API compatibility routes consumed by the web frontend."""

from .router import V1Dependencies, create_v1_media_router, create_v1_router

__all__ = ["V1Dependencies", "create_v1_router", "create_v1_media_router"]
