"""Đọc file EPUB thành cấu trúc chương / đoạn / câu để hiển thị và đọc voice.

Dùng EbookLib + BeautifulSoup. Trả về plain text đã tách câu, thuận tiện cho
việc highlight từng câu khi đọc thành tiếng.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub

# Thẻ được coi là tiêu đề (heading) trong chương
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
# Thẻ chứa nội dung văn bản dạng đoạn
_BLOCK_TAGS = {"p", "blockquote", "li"} | _HEADING_TAGS

# Tách câu: cắt sau . ! ? … (và dấu ngoặc/nháy đóng theo sau), giữ lại dấu câu.
_SENTENCE_SPLIT = re.compile(r'(?<=[.!?…。！？])["”\'’)\]]*\s+')
_WS = re.compile(r"\s+")

# --- Lọc ký hiệu không cần đọc (chú thích, dấu sao...) --------------------
# Chữ số dạng mũ (chú thích): ⁰¹²³... và các dấu * † ‡ ⁎
_SUP_CHARS = "⁰¹²³⁴⁵⁶⁷⁸⁹ⁱⁿ⁺⁻⁽⁾"
_NOISE_CHARS = "*†‡⁑⁎∗"
_SUP_RUN = re.compile("[" + re.escape(_SUP_CHARS) + "]+")
# Số chú thích trong ngoặc vuông: [12], 【12】 (chỉ chứa chữ số -> bỏ)
_BRACKET_REF = re.compile(r"[\[\uFF3B【]\s*\d{1,4}\s*[\]\uFF3D】]")
# Số chú thích trong ngoặc đơn: (1), (12), （3） — giới hạn 1–3 chữ số để
# KHÔNG xoá nhầm năm trong ngoặc như (1945).
_PAREN_REF = re.compile(r"[(\uFF08]\s*\d{1,3}\s*[)\uFF09]")
# Xoá khoảng trắng thừa trước dấu câu (do bỏ ký hiệu để lại)
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([.,;:!?…])")


def _denoise(text: str) -> str:
    """Bỏ các ký hiệu không nên đọc thành tiếng: số chú thích, dấu sao..."""
    text = _BRACKET_REF.sub("", text)
    text = _PAREN_REF.sub("", text)
    text = _SUP_RUN.sub("", text)
    for ch in _NOISE_CHARS:
        text = text.replace(ch, "")
    return text


def _clean(text: str) -> str:
    text = _denoise(text)
    text = _WS.sub(" ", text)
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
    return text.strip()


def split_sentences(text: str) -> list[str]:
    """Tách một đoạn văn thành danh sách câu (đơn giản, đủ dùng cho tiếng Việt)."""
    text = _clean(text)
    if not text:
        return []
    parts = _SENTENCE_SPLIT.split(text)
    out: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # Ghép các mẩu quá ngắn (vd số thứ tự "1.") vào câu trước cho mượt
        if out and len(p) < 3 and not p[-1:].isalnum():
            out[-1] = out[-1] + " " + p
        else:
            out.append(p)
    # Tách nhỏ câu quá dài để giảm độ trễ tổng hợp (phát sớm hơn)
    chunked: list[str] = []
    for s in out:
        chunked.extend(_split_long(s))
    return chunked


# Câu dài hơn ngưỡng này sẽ được tách tại dấu ngắt để đọc/tạo giọng theo cụm.
# Ngưỡng nhỏ -> phát sớm hơn (đỡ trễ) nhưng ngắt vụn hơn một chút.
_MAX_UNIT = 100
_CLAUSE_BREAK = re.compile(r'(?<=[,;:—–])\s+')


def _split_words(text: str) -> list[str]:
    words = text.split()
    out, cur = [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > _MAX_UNIT:
            out.append(cur)
            cur = w
        else:
            cur = (cur + " " + w) if cur else w
    if cur:
        out.append(cur)
    return out


def _split_long(sentence: str) -> list[str]:
    if len(sentence) <= _MAX_UNIT:
        return [sentence]
    pieces = _CLAUSE_BREAK.split(sentence)   # giữ dấu ngắt ở cuối mỗi vế
    grouped: list[str] = []
    cur = ""
    for p in pieces:
        if cur and len(cur) + 1 + len(p) > _MAX_UNIT:
            grouped.append(cur)
            cur = p
        else:
            cur = (cur + " " + p) if cur else p
    if cur:
        grouped.append(cur)
    out: list[str] = []
    for g in grouped:
        out.extend([g] if len(g) <= _MAX_UNIT else _split_words(g))
    return out


@dataclass
class Block:
    type: str                 # "h" (tiêu đề) hoặc "p" (đoạn văn)
    text: str = ""            # dùng cho tiêu đề
    sentences: list[str] = field(default_factory=list)  # dùng cho đoạn văn

    def to_dict(self) -> dict:
        if self.type == "h":
            return {"type": "h", "text": self.text}
        return {"type": "p", "sentences": self.sentences}


@dataclass
class Chapter:
    index: int
    title: str
    blocks: list[Block]

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "title": self.title,
            "blocks": [b.to_dict() for b in self.blocks],
        }


@dataclass
class Book:
    id: str
    title: str
    author: str
    filename: str
    has_cover: bool
    chapters: list[Chapter] = field(default_factory=list)

    def meta_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "author": self.author,
            "has_cover": self.has_cover,
            "chapter_count": len(self.chapters),
        }

    def full_dict(self) -> dict:
        d = self.meta_dict()
        d["chapters"] = [c.to_dict() for c in self.chapters]
        return d


def book_id_for(path: Path) -> str:
    return hashlib.sha1(path.name.encode("utf-8")).hexdigest()[:16]


def _strip_noise_nodes(soup: BeautifulSoup) -> None:
    """Xoá tận gốc các phần tử là chú thích/ký hiệu không cần đọc.

    Đáng tin hơn regex vì bắt đúng cấu trúc EPUB: <sup> và các neo chú thích
    (epub:type="noteref", role="doc-noteref", class chứa footnote/noteref...).
    """
    for t in soup.find_all("sup"):
        t.decompose()
    for a in soup.find_all("a"):
        try:
            ep = (a.get("epub:type") or a.get("type") or "").lower()
            role = (a.get("role") or "").lower()
            cls = " ".join(a.get("class") or []).lower()
            href = (a.get("href") or "").lower()
            txt = a.get_text(strip=True)
            is_note = (
                "noteref" in ep
                or "doc-noteref" in role
                or any(k in cls for k in ("noteref", "footnote", "fn", "note"))
                or (txt.isdigit() and any(k in href for k in ("#fn", "#note", "ftn", "footnote")))
            )
            if is_note:
                a.decompose()
        except Exception:
            continue


def _extract_blocks(soup: BeautifulSoup) -> list[Block]:
    body = soup.body or soup
    blocks: list[Block] = []
    seen_nodes = set()
    for tag in body.find_all(_BLOCK_TAGS):
        # Bỏ qua thẻ lồng đã được xử lý bởi thẻ cha (vd <li><p>)
        if id(tag) in seen_nodes:
            continue
        for child in tag.find_all(_BLOCK_TAGS):
            seen_nodes.add(id(child))
        text = _clean(tag.get_text(" ", strip=True))
        if not text:
            continue
        if tag.name in _HEADING_TAGS:
            blocks.append(Block(type="h", text=text))
        else:
            sents = split_sentences(text)
            if sents:
                blocks.append(Block(type="p", sentences=sents))
    return blocks


def _guess_chapter_title(soup: BeautifulSoup, fallback: str) -> str:
    for h in ("h1", "h2", "h3"):
        el = soup.find(h)
        if el and el.get_text(strip=True):
            return _clean(el.get_text(" ", strip=True))
    if soup.title and soup.title.get_text(strip=True):
        return _clean(soup.title.get_text(strip=True))
    return fallback


def parse_epub(path: Path) -> Book:
    book = epub.read_epub(str(path), options={"ignore_ncx": False})

    title = "Không rõ tựa"
    if book.get_metadata("DC", "title"):
        title = book.get_metadata("DC", "title")[0][0]
    author = ""
    if book.get_metadata("DC", "creator"):
        author = book.get_metadata("DC", "creator")[0][0]

    has_cover = _find_cover_bytes(book) is not None

    chapters: list[Chapter] = []
    idx = 0
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        # Bỏ qua trang điều hướng / mục lục (nav, toc) — không phải nội dung sách
        if isinstance(item, epub.EpubNav):
            continue
        props = getattr(item, "properties", None) or []
        if "nav" in props:
            continue
        name = (item.get_name() or "").lower()
        if name in ("nav.xhtml", "toc.xhtml") or name.endswith("/nav.xhtml"):
            continue
        try:
            soup = BeautifulSoup(item.get_content(), "html.parser")
        except Exception:
            continue
        _strip_noise_nodes(soup)
        blocks = _extract_blocks(soup)
        if not blocks:
            continue
        ch_title = _guess_chapter_title(soup, f"Phần {idx + 1}")
        chapters.append(Chapter(index=idx, title=ch_title, blocks=blocks))
        idx += 1

    return Book(
        id=book_id_for(path),
        title=title,
        author=author,
        filename=path.name,
        has_cover=has_cover,
        chapters=chapters,
    )


def _find_cover_bytes(book: "epub.EpubBook") -> Optional[bytes]:
    # 1) cover chuẩn qua metadata
    try:
        for item in book.get_items_of_type(ebooklib.ITEM_COVER):
            return item.get_content()
    except Exception:
        pass
    # 2) item ảnh có tên gợi ý "cover"
    try:
        for item in book.get_items_of_type(ebooklib.ITEM_IMAGE):
            name = (item.get_name() or "").lower()
            if "cover" in name:
                return item.get_content()
    except Exception:
        pass
    return None


def get_cover_bytes(path: Path) -> Optional[bytes]:
    try:
        book = epub.read_epub(str(path))
    except Exception:
        return None
    return _find_cover_bytes(book)
