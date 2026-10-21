"""mobi_parser.py — Đọc MOBI/AZW3 thành cùng cấu trúc Book như EPUB.

Chiến lược: dùng thư viện `mobi` (thuần Python, chạy tốt trên ARM) để giải nén
file .mobi ra nội dung, rồi:
  - Nếu ra .epub (mobi đời mới KF8)  -> parse bằng chính parse_epub.
  - Nếu ra .html (mobi cũ mobi7)     -> tách chương theo tiêu đề, dùng _extract_blocks.
  - Nếu ra .pdf  (print replica)     -> parse bằng parse_pdf.
Giữ nguyên id/filename theo FILE MOBI GỐC để thư viện (list/cover/xóa) hoạt động đúng.

Cài thư viện:  pip install mobi
"""
from __future__ import annotations

import shutil
from pathlib import Path

from bs4 import BeautifulSoup

from epub_parser import (
    Book, Chapter, Block, book_id_for,
    parse_epub, _extract_blocks, _strip_noise_nodes, _clean,
)
from pdf_parser import parse_pdf


def _rebrand(book: Book, original: Path) -> Book:
    """Gắn lại id/filename theo file mobi gốc; mobi chưa trích ảnh bìa -> dùng bìa tự sinh."""
    book.id = book_id_for(original)
    book.filename = original.name
    book.has_cover = False
    return book


def _chapters_from_html(html: bytes | str) -> list[Chapter]:
    """Tách HTML (mobi7) thành chương: mỗi tiêu đề (h1..h6) mở một chương mới."""
    soup = BeautifulSoup(html, "html.parser")
    _strip_noise_nodes(soup)
    blocks = _extract_blocks(soup)

    chapters: list[Chapter] = []
    cur_title: str | None = None
    cur_blocks: list[Block] = []

    def _flush():
        nonlocal cur_blocks, cur_title
        if cur_blocks or cur_title:
            idx = len(chapters)
            title = cur_title or (f"Phần {idx + 1}")
            chapters.append(Chapter(index=idx, title=title, blocks=cur_blocks))
        cur_blocks = []
        cur_title = None

    for b in blocks:
        if b.type == "h":
            # Gặp tiêu đề -> chốt chương trước, mở chương mới lấy tiêu đề này
            if cur_blocks:
                _flush()
            cur_title = b.text
        else:
            cur_blocks.append(b)
    _flush()

    if not chapters:
        chapters = [Chapter(index=0, title="Phần 1", blocks=[])]
    return chapters


def parse_mobi(path: Path) -> Book:
    try:
        import mobi
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "Chưa cài thư viện đọc MOBI. Chạy: pip install mobi"
        ) from e

    try:
        tempdir, result = mobi.extract(str(path))
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Không giải nén được file MOBI: {e}") from e

    try:
        result_path = Path(result)
        suffix = result_path.suffix.lower()

        if suffix == ".epub":
            # Đường chính: KF8 -> epub, parse đầy đủ rồi gắn lại id gốc.
            book = parse_epub(result_path)
            return _rebrand(book, path)

        if suffix == ".pdf":
            book = parse_pdf(result_path)
            return _rebrand(book, path)

        # Còn lại coi như HTML (mobi7 book.html)
        html = result_path.read_bytes()
        title = path.stem
        try:
            soup = BeautifulSoup(html, "html.parser")
            if soup.title and soup.title.get_text(strip=True):
                title = _clean(soup.title.get_text(" ", strip=True)) or title
        except Exception:  # noqa: BLE001
            pass
        return Book(
            id=book_id_for(path),
            title=title,
            author="",
            filename=path.name,
            has_cover=False,
            chapters=_chapters_from_html(html),
        )
    finally:
        # Dọn thư mục tạm mà thư viện mobi tạo ra (nội dung đã nạp hết vào Book).
        try:
            shutil.rmtree(tempdir, ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass
