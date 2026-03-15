"""Structured server-issued cursor utilities for offset-based pagination.

Offset-backed tools (get_paper_citations, get_paper_references, get_paper_authors,
get_author_papers, search_authors) encode continuation state as URL-safe base64
JSON cursors instead of raw integer offsets.

This prevents accidental cursor reuse across tools and queries, and aligns with MCP
best practices for opaque server-issued continuation tokens.

Bulk-search cursors (provider tokens) are NOT processed here; they pass through
the dispatch layer unchanged.
"""

import base64
import hashlib
import json
from dataclasses import dataclass

CURSOR_VERSION = 1
PROVIDER = "semantic_scholar"
SUPPORTED_VERSIONS: frozenset[int] = frozenset({CURSOR_VERSION})

# Offset-backed tools that use structured cursors
OFFSET_TOOLS: frozenset[str] = frozenset(
    {
        "get_paper_citations",
        "get_paper_references",
        "get_paper_authors",
        "get_author_papers",
        "search_authors",
    }
)

# Arguments that uniquely identify the result stream for each offset-backed tool.
# Only these args are included in the context hash; limit/fields/cursor are excluded
# because they do not change which underlying dataset is being paged through.
STREAM_CONTEXT_KEYS: dict[str, tuple[str, ...]] = {
    "get_paper_citations": ("paper_id",),
    "get_paper_references": ("paper_id",),
    "get_paper_authors": ("paper_id",),
    "get_author_papers": ("author_id", "publication_date_or_year"),
    "search_authors": ("query",),
}


@dataclass
class CursorState:
    """Decoded state carried inside a structured pagination cursor.

    Attributes
    ----------
    tool:
        Name of the MCP tool that issued this cursor.
    provider:
        Data provider name (always ``"semantic_scholar"`` for offset tools).
    offset:
        Integer page offset to pass to the next API call.
    version:
        Schema version for forward-compatibility.
    context_hash:
        Short SHA-256 hex digest of the stream-defining query arguments.
        Used to detect cursor reuse across different queries on the same tool.
        ``None`` for legacy cursors that predate context binding.
    """

    tool: str
    provider: str
    offset: int
    version: int = CURSOR_VERSION
    context_hash: str | None = None


def encode_cursor(payload: dict) -> str:
    """Encode a cursor payload dict as a URL-safe base64 JSON string.

    Parameters
    ----------
    payload:
        Dictionary with at minimum the keys ``tool``, ``provider``,
        ``offset``, and ``version``.

    Returns
    -------
    str
        URL-safe base64-encoded JSON cursor string.
    """
    json_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(json_bytes).decode("ascii")


def decode_cursor(cursor: str) -> CursorState:
    """Decode a structured cursor string into a :class:`CursorState`.

    Parameters
    ----------
    cursor:
        A URL-safe base64-encoded JSON cursor string as produced by
        :func:`encode_cursor`.

    Returns
    -------
    CursorState
        The decoded cursor state.

    Raises
    ------
    ValueError
        If the cursor cannot be decoded or is missing required fields.
    """
    try:
        json_bytes = base64.urlsafe_b64decode(cursor.encode("ascii"))
        payload = json.loads(json_bytes)
    except Exception as exc:
        raise ValueError(
            f"Corrupted pagination cursor {cursor!r}: cannot decode. "
            "Restart the request without a cursor."
        ) from exc

    try:
        return CursorState(
            tool=payload["tool"],
            provider=payload["provider"],
            offset=int(payload["offset"]),
            version=int(payload.get("version", CURSOR_VERSION)),
            context_hash=payload.get("context_hash"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"Corrupted pagination cursor {cursor!r}: missing required fields. "
            "Restart the request without a cursor."
        ) from exc


def is_legacy_offset(cursor: str) -> bool:
    """Return ``True`` if *cursor* looks like a legacy integer offset string.

    Legacy offset cursors are plain stringified integers, e.g. ``"100"``.
    Structured cursors are URL-safe base64 JSON and will not parse as integers.

    Parameters
    ----------
    cursor:
        The cursor string to inspect.
    """
    try:
        int(cursor)
        return True
    except (ValueError, TypeError):
        return False


def compute_context_hash(tool: str, args: dict) -> str | None:
    """Compute a short hash binding a cursor to the specific result stream.

    Hashes the subset of *args* that uniquely identify the stream (e.g.
    ``paper_id`` for citation/reference tools, ``query`` for author search).
    Pagination-only arguments such as ``cursor``, ``limit``, and ``fields``
    are intentionally excluded because they do not change which dataset is
    being paged through.

    Parameters
    ----------
    tool:
        Name of the MCP tool for which to compute the hash.
    args:
        Validated argument dict (as returned by ``model_dump``).

    Returns
    -------
    str or None
        A 16-character hex digest, or ``None`` if the tool has no registered
        stream context keys (should not happen for offset-backed tools).
    """
    keys = STREAM_CONTEXT_KEYS.get(tool)
    if keys is None:
        return None
    context = {k: args.get(k) for k in keys}
    payload = json.dumps(context, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def cursor_from_offset(
    tool: str,
    offset: int,
    context_hash: str | None = None,
) -> str:
    """Build a structured cursor encoding *offset* for *tool*.

    Parameters
    ----------
    tool:
        Name of the MCP tool issuing the cursor.
    offset:
        Next page offset.
    context_hash:
        Optional short hash of the stream-defining query arguments, as
        produced by :func:`compute_context_hash`.  When present it allows
        the server to detect cursor reuse across different queries on the
        same tool.

    Returns
    -------
    str
        URL-safe base64 cursor string.
    """
    payload: dict = {
        "tool": tool,
        "provider": PROVIDER,
        "offset": offset,
        "version": CURSOR_VERSION,
    }
    if context_hash is not None:
        payload["context_hash"] = context_hash
    return encode_cursor(payload)
