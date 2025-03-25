"""Templateer2 package.

Mini template generation with LLM enhancement
"""

from __future__ import annotations

from templateer2._internal.cli import get_parser, main

__all__: list[str] = ["get_parser", "main"]
