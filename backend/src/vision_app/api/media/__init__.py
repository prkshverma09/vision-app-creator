"""Media API router factory."""

from .router import MediaDependencies, create_media_router, add_media_exception_handlers

__all__ = ["MediaDependencies", "create_media_router", "add_media_exception_handlers"]
