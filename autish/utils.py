"""Shared utilities for autish commands."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

import typer

_SEP = "---"


def echo_padded(content: str) -> None:
    """Print *content* wrapped in --- separators with surrounding blank lines."""
    typer.echo("")
    typer.echo(_SEP)
    typer.echo(content)
    typer.echo(_SEP)
    typer.echo("")


# Markdown link support for encik and vorto references


@dataclass
class MarkdownLink:
    """Represents a parsed markdown link."""

    text: str  # Link display text
    link_type: str  # 'encik' or 'vorto'
    uuid: str  # Target UUID


def parse_markdown_links(text: str) -> list[MarkdownLink]:
    """Extract markdown links in format [text](ec#uuid) or [text](vt#uuid).

    Args:
        text: Text possibly containing markdown links.

    Returns:
        List of MarkdownLink objects found in text.
    """
    links: list[MarkdownLink] = []
    if not text:
        return links

    # Pattern: [any text](ec#uuid) or [any text](vt#uuid)
    # Where uuid is 8 hex characters
    pattern = r'\[([^\]]+)\]\(([a-z]{2})#([a-f0-9]{8})\)'
    matches = re.finditer(pattern, text)

    for match in matches:
        display_text = match.group(1)
        link_type_abbr = match.group(2)
        uuid = match.group(3)

        link_type = 'encik' if link_type_abbr == 'ec' else 'vorto'
        links.append(MarkdownLink(text=display_text, link_type=link_type, uuid=uuid))

    return links


def validate_link_targets(
    links: list[MarkdownLink],
    encik_uuids: set[str] | None = None,
    vorto_uuids: set[str] | None = None,
) -> list[MarkdownLink]:
    """Filter links to only those with valid target UUIDs.

    Args:
        links: List of parsed MarkdownLink objects.
        encik_uuids: Set of valid encik UUIDs (None = skip validation).
        vorto_uuids: Set of valid vorto UUIDs (None = skip validation).

    Returns:
        Filtered list of links with valid targets.
    """
    valid_links = []
    for link in links:
        if link.link_type == 'encik' and encik_uuids is not None:
            if link.uuid in encik_uuids:
                valid_links.append(link)
        elif link.link_type == 'vorto' and vorto_uuids is not None:
            if link.uuid in vorto_uuids:
                valid_links.append(link)
        else:
            # If no validation set provided, keep the link
            valid_links.append(link)

    return valid_links


def render_markdown_links_as_rich(text: str) -> object:
    """Render markdown links as Rich Text objects.

    Converts [text](ec#uuid) and [text](vt#uuid) patterns to Rich clickable links.

    Args:
        text: Text possibly containing markdown links.

    Returns:
        Rich Text object with links if links found, otherwise original text.
    """
    # Import here to avoid circular dependency
    from rich.text import Text

    links = parse_markdown_links(text)
    if not links:
        return text

    # Build Rich Text with links
    rich_text = Text()
    last_pos = 0

    # Find all link patterns in text
    pattern = r'\[([^\]]+)\]\(([a-z]{2})#([a-f0-9]{8})\)'
    for match in re.finditer(pattern, text):
        # Add text before link
        rich_text.append(text[last_pos : match.start()])

        link_text = match.group(1)
        link_type = "encik" if match.group(2) == "ec" else "vorto"
        uuid = match.group(3)

        # Build link URL
        link_url = f"{link_type}#{uuid}"
        rich_text.append(link_text, style=f"link {link_url}")

        last_pos = match.end()

    # Add remaining text
    rich_text.append(text[last_pos:])

    return rich_text


# ============================================================================
# Search and Fuzzy Matching Utilities
# ============================================================================


def normalize_oe(text: str) -> str:
    """Fold œ/Œ → oe/OE for case-insensitive search comparisons."""
    return text.replace("œ", "oe").replace("Œ", "OE")


def fold_search_text(text: str) -> str:
    """Normalize text for accent-insensitive, case-insensitive search.
    
    Removes accents, handles œ → oe, converts to lowercase.
    This is the standard folding used across autish for consistent search behavior.
    """
    folded_oe = normalize_oe(str(text or ""))
    normalized = unicodedata.normalize("NFKD", folded_oe)
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return stripped.casefold()


def fuzzy_match_score(query: str, target: str, threshold: float = 0.62) -> float | None:
    """Calculate fuzzy match score between query and target text.
    
    Returns a float between 0 and 1 if score >= threshold, else None.
    Both texts are folded before comparison.
    """
    q = fold_search_text(query.strip())
    t = fold_search_text(target.strip())
    
    if not q or not t:
        return None
    
    ratio = SequenceMatcher(None, q, t).ratio()
    return ratio if ratio >= threshold else None


def fuzzy_match_ignore_whitespace(
    query: str, target: str, threshold: float = 0.62
) -> float | None:
    """Calculate fuzzy match score ignoring spaces and punctuation.
    
    Removes spaces, punctuation, and accents before comparison.
    Useful for matching names, titles, and other text that may have formatting
    variations.
    """
    q = re.sub(r"[\s\W]+", "", fold_search_text(query.strip()))
    t = re.sub(r"[\s\W]+", "", fold_search_text(target.strip()))
    
    if not q or not t:
        return None
    
    ratio = SequenceMatcher(None, q, t).ratio()
    return ratio if ratio >= threshold else None


def wildcard_match(query: str, target: str) -> bool:
    """Simple wildcard match with * support.
    
    Converts wildcard pattern to regex and matches against target.
    Example: "*.txt" matches "file.txt", "test.txt", etc.
    """
    pattern = re.escape(query).replace(r"\*", ".*")
    try:
        return bool(re.match(f"^{pattern}$", target, re.IGNORECASE))
    except re.error:
        return False


def substring_match_folded(query: str, target: str) -> bool:
    """Substring match with folded (normalized, lowercased) text.
    
    Useful for exact-ish substring search with case/accent insensitivity.
    """
    q = fold_search_text(query.strip())
    t = fold_search_text(target.strip())
    return q in t if q and t else False


def filter_entries_by_text(
    entries: list[dict],
    query: str,
    *,
    text_key: str = "teksto",
    limit: int = 50,
    use_whitespace_ignore: bool = False,
) -> list[dict]:
    """Filter and rank entries by fuzzy text match on a specific key.
    
    Args:
        entries: List of dicts to search
        query: Search query
        text_key: Dict key containing the text to search (e.g., "teksto", "titulo")
        limit: Max results to return
        use_whitespace_ignore: If True, ignore spaces/punctuation in matching
    
    Returns:
        Sorted list of matched entries, highest match score first
    """
    q = query.strip()
    if not q:
        return []
    
    scored: list[tuple[float, dict]] = []
    match_fn = (
        fuzzy_match_ignore_whitespace
        if use_whitespace_ignore
        else fuzzy_match_score
    )
    
    for entry in entries:
        text = entry.get(text_key) or ""
        if not text:
            continue
        score = match_fn(q, str(text))
        if score is not None:
            scored.append((score, entry))
    
    scored.sort(key=lambda item: item[0], reverse=True)
    return [entry for _, entry in scored[:limit]]

