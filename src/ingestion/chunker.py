"""Recursive chunker for RFC / markdown networking docs (hybrid chunking)."""
from __future__ import annotations

import re


def _split_recursive(text: str, separators: list[str]) -> list[str]:
    """Recursively split text by ordered separators."""
    if not separators:
        return [text] if text else []
    sep = separators[0]
    rest = separators[1:]
    # Use regex-escaped literal split, keeping content (no empty strings).
    parts = re.split(re.escape(sep), text)
    out: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(p) <= 0:
            continue
        # If still too long handled by caller; recurse only when sep present
        if sep in text and len(separators) > 1 and (len(p) > 0):
            sub = _split_recursive(p, rest)
            out.extend(sub if sub else [p])
        else:
            out.append(p)
    return out


def chunk_text(
    text: str,
    chunk_size: int = 500,
    overlap: int = 50,
    separators: list[str] | None = None,
) -> list[str]:
    """Split text into chunks of ~chunk_size chars with char overlap.

    Strategy: recursive split on ["\\n\\n", "\\n", ". ", " "] then
    greedily merge small pieces up to chunk_size, applying overlap
    by carrying the tail of the previous chunk.
    """
    if not text or not text.strip():
        return []
    if separators is None:
        separators = ["\n\n", "\n", ". ", " "]
    pieces = _split_recursive(text.strip(), separators)
    # Greedy merge
    merged: list[str] = []
    buf = ""
    for piece in pieces:
        candidate = (buf + " " + piece).strip() if buf else piece
        if len(candidate) <= chunk_size:
            buf = candidate
        else:
            if buf:
                merged.append(buf)
            # hard-split overlong single piece
            while len(piece) > chunk_size:
                merged.append(piece[:chunk_size])
                piece = piece[chunk_size - overlap :]
            buf = piece
    if buf:
        merged.append(buf)
    # Apply overlap between adjacent chunks
    if overlap > 0 and len(merged) > 1:
        overlapped = [merged[0]]
        for i in range(1, len(merged)):
            tail = overlapped[-1][-overlap:]
            overlapped.append((tail + " " + merged[i]).strip())
        return overlapped
    return merged


def chunk_markdown(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Markdown-aware chunking: split on headers first, then recursive."""
    if not text or not text.strip():
        return []
    sections = re.split(r"(?m)^#{1,3}\s+.*$", text)
    headers = re.findall(r"(?m)^#{1,3}\s+.*$", text)
    blocks: list[str] = []
    for i, sec in enumerate(sections):
        prefix = headers[i - 1] if i > 0 and (i - 1) < len(headers) else ""
        block = (prefix + "\n" + sec).strip() if prefix else sec.strip()
        if block:
            blocks.append(block)
    chunks: list[str] = []
    for block in blocks:
        chunks.extend(chunk_text(block, chunk_size=chunk_size, overlap=0))
    if overlap > 0 and len(chunks) > 1:
        overlapped = [chunks[0]]
        for i in range(1, len(chunks)):
            tail = overlapped[-1][-overlap:]
            overlapped.append((tail + " " + chunks[i]).strip())
        return overlapped
    return chunks
