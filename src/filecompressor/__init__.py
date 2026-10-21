"""Offline compression for images, PDFs and Office documents."""


class SkipFile(Exception):
    """Raised when a file can't be compressed for an expected reason (e.g. encrypted)."""
