"""Shared memory-context markup constants and untrusted-text escaping.

Stored observations can contain attacker-influenced text (malicious tool
output, poisoned documents). When such text is interpolated inside the
delimited ``<openlmlib-memory-context>`` block, a raw closing delimiter in
the content would terminate the block early and let the remainder be read
as out-of-bound instructions (stored prompt injection).

Renderers must interpolate untrusted fields only through
:func:`escape_untrusted` and emit delimiters only through these constants.
"""

from __future__ import annotations

from typing import Any

MEMORY_CONTEXT_OPEN = "<openlmlib-memory-context>"
MEMORY_CONTEXT_CLOSE = "</openlmlib-memory-context>"


def escape_untrusted(value: Any) -> str:
    """Neutralize angle brackets so stored text cannot forge context markup.

    ``&`` is escaped first to avoid double-escaping. Escaped entities survive
    downstream caveman compression, which only drops filler words.
    """
    if value is None:
        return ""
    text = str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
