"""pdf_parser.py — Đọc PDF thành cùng cấu trúc Book như EPUB.

Chiến lược:
- Rút text từng trang bằng pypdf (thuần Python, chạy tốt trên ARM).
- Nếu PDF có outline (bookmark/mục lục) -> chia chương theo bookmark.
- Không có outline -> gộp mỗi PAGES_PER_CHAPTER trang thành một "Phần".
- Mỗi đoạn -> Block "p" với split_sentences (dùng lại logic của epub_parser).
- PDF scan ảnh (không rút được chữ) -> báo lỗi để người dùng biết.
"""
from __future__ import annotations
import re
from pathlib import Path

from epub_parser import Book, Chapter, Block, split_sentences, book_id_for

PAGES_PER_CHAPTER = 8


def _dehyphen_join(lines: list[str]) -> str:
    out: list[str] = []
    for i, ln in enumerate(lines):
        ln = ln.rstrip()
        if ln.endswith("-") and i + 1 < len(lines):
            out.append(ln[:-1])                 # nối từ bị gạch nối cuối dòng
        else:
            out.append(ln + " ")
    return "".join(out)


def _page_paragraphs(text: str) -> list[str]:
    """Gộp các dòng gãy của PDF thành đoạn; tách đoạn theo dòng trống."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    result: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        joined = _dehyphen_join(para.split("\n"))
        joined = re.sub(r"[ \t]+", " ", joined).strip()
        if joined:
            result.append(joined)
    return result


def _make_chapter(index: int, title: str, page_texts: list[str]) -> Chapter:
    blocks: list[Block] = []
    for pt in page_texts:
        for para in _page_paragraphs(pt):
            sents = split_sentences(para)
            if sents:
                blocks.append(Block(type="p", sentences=sents))
    return Chapter(index=index, title=title, blocks=blocks)


def _chapters_from_outline(reader, page_texts, n) -> list[Chapter]:
    entries: list[tuple[str, int]] = []

    def walk(items):
        for it in items:
            if isinstance(it, list):
                walk(it)
            else:
                try:
                    pg = reader.get_destination_page_number(it)
                    ttl = getattr(it, "title", None) or ""
                    if pg is not None:
                        entries.append((str(ttl).strip(), int(pg)))
                except Exception:
                    pass

    try:
        walk(reader.outline)
    except Exception:
        return []
    entries = [e for e in entries if 0 <= e[1] < n]
    entries.sort(key=lambda e: e[1])
    if len(entries) < 2:
        return []
    chapters: list[Chapter] = []
    for i, (ttl, start) in enumerate(entries):
        end = entries[i + 1][1] if i + 1 < len(entries) else n
        ch = _make_chapter(i, ttl or f"Phần {i + 1}", page_texts[start:end])
        if ch.blocks:
            chapters.append(ch)
    return chapters


def parse_pdf(path: Path) -> Book:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    n = len(reader.pages)
    page_texts: list[str] = []
    for pg in reader.pages:
        try:
            page_texts.append(pg.extract_text() or "")
        except Exception:
            page_texts.append("")

    meta = reader.metadata or {}
    title = (getattr(meta, "title", None) or "").strip() or path.stem
    author = (getattr(meta, "author", None) or "").strip()

    chapters = _chapters_from_outline(reader, page_texts, n)
    if not chapters:                                    # không có outline -> gộp theo trang
        chapters = []
        idx = 0
        for start in range(0, n, PAGES_PER_CHAPTER):
            ch = _make_chapter(idx, f"Phần {idx + 1}", page_texts[start:start + PAGES_PER_CHAPTER])
            if ch.blocks:
                chapters.append(ch)
                idx += 1

    if not chapters:
        raise ValueError("PDF không có văn bản trích xuất được (có thể là bản scan ảnh).")

    for i, c in enumerate(chapters):                    # đánh lại index liên tục
        c.index = i

    return Book(id=book_id_for(path), title=title, author=author,
                filename=path.name, has_cover=False, chapters=chapters)
