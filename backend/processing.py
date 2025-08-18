from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import re

import fitz  # PyMuPDF
from sentence_transformers import SentenceTransformer


# Lazy-loaded global embedder to avoid re-downloading/re-initializing on each call
_EMBEDDER: Optional[SentenceTransformer] = None


def _get_embedder(model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> SentenceTransformer:
    global _EMBEDDER
    if _EMBEDDER is None:
        _EMBEDDER = SentenceTransformer(model_name)
    return _EMBEDDER


def _split_paragraphs(text: str) -> List[str]:
    """Split text into paragraphs using blank lines as separators."""
    # Normalize line breaks and split on blank lines
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]
    return paragraphs


def _chunk_text(text: str, max_chars: int = 800, overlap: int = 100) -> List[str]:
    """Chunk text into ~max_chars with a small overlap, trying to split at natural boundaries.

    - Cleans whitespace
    - Attempts to find a split point near the end of each chunk on punctuation/space
    """
    s = re.sub(r"\s+", " ", text).strip()
    if not s:
        return []

    chunks: List[str] = []
    n = len(s)
    start = 0
    while start < n:
        end = min(start + max_chars, n)
        if end < n:
            window = s[start:end]
            # Prefer split on sentence boundary, then space/comma
            candidates = [window.rfind(". "), window.rfind("? "), window.rfind("! "), window.rfind(", "), window.rfind(" ")]
            cut = max(candidates)
            if cut != -1 and cut > int(0.5 * max_chars):
                end = start + cut + 1  # include the split character
        chunk = s[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        # Overlap for context continuity
        start = max(0, end - overlap)
    return chunks


def _assemble_lines(page: fitz.Page) -> Tuple[List[Dict[str, Any]], float]:
    """Return ordered lines with average font size and the median font size for the page.
    Each line: { text: str, size: float }
    """
    data = page.get_text("dict")
    lines: List[Dict[str, Any]] = []
    sizes: List[float] = []
    for block in data.get("blocks", []) or []:
        for line in block.get("lines", []) or []:
            spans = line.get("spans", []) or []
            t = "".join([s.get("text", "") for s in spans]).strip()
            if not t:
                continue
            szs = [float(s.get("size", 0.0)) for s in spans if s.get("text")]
            avg = (sum(szs) / len(szs)) if szs else 0.0
            lines.append({"text": t, "size": avg})
            if avg > 0:
                sizes.append(avg)
    if sizes:
        sizes_sorted = sorted(sizes)
        mid = len(sizes_sorted) // 2
        median = sizes_sorted[mid] if len(sizes_sorted) % 2 == 1 else (sizes_sorted[mid-1] + sizes_sorted[mid]) / 2.0
    else:
        median = 0.0
    return lines, median


def _looks_like_heading(text: str, size: float, median_size: float) -> bool:
    t = (text or "").strip()
    if len(t) < 4:
        return False
    if t.endswith('.') or t.endswith('!') or t.endswith('?'):
        # headings rarely end with sentence punctuation
        return False
    # Size threshold: noticeably larger than median
    bigger = (median_size > 0 and (size >= median_size + 1.0 or size >= 1.15 * median_size))
    # Pattern hints: numbered headings or many capitalized words
    numbered = bool(re.match(r"^(\d+\.)+(\s|$)|^\d+\s+", t))
    letters = [c for c in t if c.isalpha()]
    uppers = [c for c in letters if c.isupper()]
    cap_ratio = (len(uppers) / len(letters)) if letters else 0.0
    capitalized = cap_ratio >= 0.35
    shortish = len(t) <= 120
    return shortish and (bigger or numbered or capitalized)


def _sections_from_toc(doc: fitz.Document) -> Optional[List[Dict[str, Any]]]:
    """Build sections from PDF TOC (table of contents) if available.
    Returns a list of sections [{title, page, text}] or None if TOC is absent/empty.
    """
    try:
        toc = doc.get_toc(simple=True)  # list of [level, title, page]
    except Exception:
        toc = None
    if not toc:
        return None

    # Normalize entries and ensure page numbers are valid (1-based)
    entries: List[Tuple[int, str, int]] = []
    for e in toc:
        try:
            level = int(e[0])
            title = str(e[1] or "").strip()
            page = int(e[2])
            if title and page >= 1 and page <= len(doc):
                entries.append((level, title, page))
        except Exception:
            continue
    if not entries:
        return None

    # Sort by page number to ensure reading order
    entries.sort(key=lambda x: x[2])

    # Build sections: each entry captures content from its page start up to next entry's page-1 (inclusive)
    sections: List[Dict[str, Any]] = []
    for i, (level, title, start_page) in enumerate(entries):
        end_page = (entries[i + 1][2] - 1) if (i + 1 < len(entries)) else len(doc)
        # Extract text across page range
        buf: List[str] = []
        for p in range(start_page - 1, end_page):  # doc is 0-based
            try:
                txt = doc[p].get_text("text") or ""
            except Exception:
                txt = ""
            if txt.strip():
                buf.append(txt.strip())
        body = "\n".join(buf).strip()
        if body:
            sections.append({
                "title": title,
                "text": body,
                "page": start_page,
            })
    return sections or None


def process_pdf(file_path: str, max_chars: int = 800, overlap: int = 100) -> List[Dict[str, Any]]:
    """Process a PDF into section embeddings when possible (heading + following content).

    Falls back to paragraph chunking if headings cannot be detected.

    Args:
        file_path: Path to a PDF file.
        max_chars: Not used for sectioning; used for fallback chunking.
        overlap: Overlap for fallback chunking.

    Returns:
        A list of dicts: { "text_chunk": str, "embedding": List[float], "page_number": int, "section_title"?: str, "section_index"?: int }
        page_number is 1-based (first page where section starts).
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"PDF not found: {file_path}")

    doc = fitz.open(path)
    try:
        # First pass: try to extract sections using TOC if present; else use heading heuristics
        sections: Optional[List[Dict[str, Any]]] = _sections_from_toc(doc)
        current: Optional[Dict[str, Any]] = None

        if sections is None:
            sections = []
            for page_index in range(len(doc)):
                page = doc[page_index]
                lines, median = _assemble_lines(page)
                if not lines:
                    continue
                for ln in lines:
                    t = (ln.get("text") or "").strip()
                    sz = float(ln.get("size") or 0.0)
                    if _looks_like_heading(t, sz, median):
                        # start a new section
                        current = {
                            "title": t,
                            "text": "",
                            "page": page_index + 1,
                        }
                        sections.append(current)
                    else:
                        if current is None:
                            # implicit intro section if content appears before any heading
                            current = {
                                "title": "Introduction",
                                "text": "",
                                "page": page_index + 1,
                            }
                            sections.append(current)
                        # append content line
                        if current["text"]:
                            current["text"] += "\n"
                        current["text"] += t

        # Prune empty or tiny sections
        sections = [s for s in sections if (s.get("text") or "").strip()]

        if not sections:
            # Fallback: paragraph chunking
            texts: List[str] = []
            meta: List[Dict[str, Any]] = []
            for page_index in range(len(doc)):
                page = doc[page_index]
                text = page.get_text("text") or ""
                if not text.strip():
                    continue
                for para in _split_paragraphs(text):
                    for chunk in _chunk_text(para, max_chars=max_chars, overlap=overlap):
                        texts.append(chunk)
                        meta.append({"page_number": page_index + 1})
            if not texts:
                return []
            model = _get_embedder()
            embeddings = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
            results: List[Dict[str, Any]] = []
            for chunk, emb, m in zip(texts, embeddings, meta):
                results.append({
                    "text_chunk": chunk,
                    "embedding": emb.tolist(),
                    "page_number": m["page_number"],
                })
            return results

        # Embed sections
        texts = [s.get("text", "") for s in sections]
        model = _get_embedder()
        embeddings = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        results: List[Dict[str, Any]] = []
        for idx, (sec, emb) in enumerate(zip(sections, embeddings)):
            results.append({
                "text_chunk": sec.get("text", ""),
                "embedding": emb.tolist(),
                "page_number": int(sec.get("page") or 1),
                "section_title": sec.get("title") or None,
                "section_index": idx,
            })
        return results
    finally:
        doc.close()
