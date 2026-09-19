"""Explicit media errors. Every decoder failure maps to one of these."""


class MediaError(Exception):
    """Base class for all media probe/decode/extraction failures."""

    code = "media_error"


class InvalidMediaError(MediaError):
    """Unreadable container, missing video stream, or non-local input."""

    code = "invalid_media"


class UnsupportedMediaError(MediaError):
    """Valid media that violates a supported-codec/rate policy."""

    code = "unsupported_media"


class OversizedMediaError(MediaError):
    """Media exceeds byte, duration, pixel, or frame-count limits."""

    code = "oversized_media"


class DecoderUnavailableError(MediaError):
    """ffmpeg/ffprobe binaries are missing from the environment."""

    code = "decoder_unavailable"


class DecodeTimeoutError(MediaError):
    """Probe, decode, or extraction exceeded its wall-clock deadline."""

    code = "decode_timeout"


class DecodeError(MediaError):
    """Decode failed mid-stream: unexpected EOF, gap, or decoder crash."""

    code = "decode_error"


class EndOfMediaError(MediaError):
    """Requested window/sample lies entirely past the end of the media."""

    code = "end_of_media"
