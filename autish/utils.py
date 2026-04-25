"""Shared utilities for autish commands."""

from __future__ import annotations

import re
from dataclasses import dataclass

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
