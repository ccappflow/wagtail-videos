"""Backward-compatibility shim.

wagtailvideos 7.x moved the ffmpeg helpers into
``wagtailvideos.transcoders.ffmpeg.ffmpeg``. This module re-exports their
public API under the historical import path (``from wagtailvideos import
ffmpeg``) so existing integrations keep working after upgrading.
"""
from wagtailvideos.transcoders.ffmpeg.ffmpeg import (  # noqa: F401
    VideoStats, get_stats, get_thumbnail, installed)

__all__ = ["VideoStats", "get_stats", "get_thumbnail", "installed"]
