"""pdf_units.py - PDF -> danh sách "unit" (câu) để đọc bằng TTS.

Mỗi unit gồm: i (thứ tự), p (số thứ tự đoạn), ch (chương), page, hash, text, say.
`text` là nguyên văn (để xem lại), `say` là bản đã chuẩn hoá (text_norm.py) để đưa vào TTS.
`hash` = khóa cache của `say`, chỉ dùng lúc render. Đổi quy tắc làm sạch / tách câu / chuẩn hoá
thì hash của câu bị ảnh hưởng đổi theo, và chỉ những câu đó phải render lại.
"""
import hashlib
import os
import re
import unicodedata
from collections import Counter

try:
    import pymupdf as fitz
except ImportError:  # PyMuPDF bản cũ
    import fitz

from text_norm import normalize_for_tts, is_speakable

RULES_VERSION = "pdfu-3"

# --------------------------------------------------------------------------
# Khóa cache: sha1 của câu. Cùng một câu (cùng giọng) chỉ phải render một lần.
# --------------------------------------------------------------------------
def unit_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------
# Làm sạch text
# --------------------------------------------------------------------------
_LIGATURES = {"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl"}
_URL = re.compile(r"(https?://|www\.)\S+", re.I)
_CTRL = re.compile(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f\u00ad\u200b-\u200f\u2028\u2029\ufeff]")
_WS = re.compile(r"[ \t\u00a0\u2009\u202f]+")
_BULLET = re.compile(r"^[\u2022\u25cf\u25aa\u25e6\u2023\u2043\*\-–—]+\s+")
_TERMINAL = re.compile(r"[.!?…:;][\"”’')\]]*$")


def clean_text(s: str) -> str:
    # NFC rất quan trọng với tiếng Việt: PDF hay trả về dạng tổ hợp (NFD)
    s = unicodedata.normalize("NFC", s)
    for k, v in _LIGATURES.items():
        s = s.replace(k, v)
    s = _CTRL.sub("", s)
    s = _URL.sub("", s)
    s = _WS.sub(" ", s)
    return s.strip()


def _has_speakable(s: str) -> bool:
    return any(ch.isalnum() for ch in s)


# --------------------------------------------------------------------------
# Trích text từ PDF
# --------------------------------------------------------------------------
def _ocr_blocks(page, lang, dpi):
    """OCR 1 trang bằng tesseract CLI (KHÔNG dùng get_textpage_ocr của PyMuPDF: nó làm
    mất khoảng trắng sau chữ có dấu tiếng Việt - đã thử, 'Hồ Chí' thành 'HồChí').
    Không có tọa độ thật, nên đoạn đầu/cuối trang được gán vị trí lề để còn lọc header/footer."""
    import shutil
    import subprocess
    if not shutil.which("tesseract"):
        raise RuntimeError("Chưa cài tesseract: apt-get install -y tesseract-ocr tesseract-ocr-vie")
    png = page.get_pixmap(dpi=dpi).tobytes("png")
    r = subprocess.run(["tesseract", "stdin", "stdout", "-l", lang, "--psm", "3"],
                       input=png, capture_output=True)
    text = r.stdout.decode("utf-8", errors="ignore")
    chunks = [c.strip() for c in re.split(r"\n\s*\n", text) if c.strip()]
    h = page.rect.height
    out = []
    for k, c in enumerate(chunks):
        if k == 0:
            out.append((0.0, h * 0.05, c))
        elif k == len(chunks) - 1:
            out.append((h * 0.95, h, c))
        else:
            out.append((h * 0.3, h * 0.7, c))
    return out


def _page_blocks(page, ocr, ocr_lang, ocr_dpi=300):
    """Trả về list (y0, y1, text) của các block văn bản, theo thứ tự đọc của PDF."""
    if ocr and len(page.get_text("text").strip()) < 30:
        return _ocr_blocks(page, ocr_lang, ocr_dpi)
    raw = page.get_text("blocks")
    out = []
    for b in raw:
        if len(b) >= 7 and b[6] != 0:  # bỏ block ảnh
            continue
        txt = b[4]
        if txt and txt.strip():
            out.append((b[1], b[3], txt))
    return out


def _sig(text):
    """Chữ ký để phát hiện header/footer lặp: số -> '#', chữ thường, gọn khoảng trắng."""
    return re.sub(r"\d+", "#", _WS.sub(" ", text.strip().lower()))


def extract_paragraphs(path, ocr=False, ocr_lang="vie", dehyphen="keep", margin=0.07, ocr_dpi=300):
    """-> (paragraphs, n_pages, info). paragraphs = list[dict(text, page)].

    dehyphen: 'keep' giữ dấu '-' ở cuối dòng (an toàn với tiếng Việt, vì tiếng Việt
              không ngắt từ giữa âm tiết); 'join' nối liền (hợp với sách tiếng Anh).
    margin:   phần trăm chiều cao trang ở trên/dưới coi là vùng header/footer.
    """
    doc = fitz.open(path)
    n = len(doc)
    pages = []
    for pno in range(n):
        page = doc[pno]
        h = page.rect.height
        blocks = _page_blocks(page, ocr, ocr_lang, ocr_dpi)
        pages.append((pno, h, blocks))

    # phát hiện header/footer: block nằm ở vùng lề và lặp trên >= 30% số trang (tối thiểu 3)
    cnt = Counter()
    for pno, h, blocks in pages:
        seen = set()
        for y0, y1, t in blocks:
            if y1 < h * margin * 2 or y0 > h * (1 - margin * 2):
                seen.add(_sig(t))
        cnt.update(seen)
    min_rep = max(3, int(0.3 * n))
    repeated = {s for s, c in cnt.items() if c >= min_rep and len(s) < 120}

    dropped = 0
    paras = []
    for pno, h, blocks in pages:
        for y0, y1, t in blocks:
            in_margin = y1 < h * margin * 2 or y0 > h * (1 - margin * 2)
            if in_margin and _sig(t) in repeated:
                dropped += 1
                continue
            if in_margin and re.fullmatch(r"\s*[\divxlcdm]{1,6}\s*", t.strip().lower()):
                dropped += 1  # số trang trơ trọi
                continue
            t = t.replace("\r", "")
            t = re.sub(r"-\n", "-" if dehyphen == "keep" else "", t)
            t = t.replace("\n", " ")
            t = clean_text(t)
            t = _BULLET.sub("", t)
            if not _has_speakable(t):
                continue
            # đoạn văn bị ngắt giữa chừng (sang block/trang mới): nối lại
            if paras and not _TERMINAL.search(paras[-1]["text"]) and t[:1].islower():
                paras[-1]["text"] += " " + t
            else:
                paras.append({"text": t, "page": pno + 1})
    info = {"dropped_blocks": dropped, "repeated_patterns": len(repeated)}
    return paras, n, info


def extract_chapters(path, n_pages, fallback_every=20):
    """Chương theo mục lục PDF (cấp 1). Không có TOC -> chia mỗi `fallback_every` trang.
    Lưu ý: mốc chương chỉ chính xác đến mức TRANG."""
    doc = fitz.open(path)
    toc = [t for t in doc.get_toc() if t[0] == 1 and 1 <= t[2] <= n_pages]
    chapters = []
    if toc:
        if toc[0][2] > 1:
            chapters.append({"title": "(Mở đầu)", "start_page": 1})
        for _, title, pg in toc:
            if chapters and chapters[-1]["start_page"] == pg:
                chapters[-1]["title"] += " / " + clean_text(title)
            else:
                chapters.append({"title": clean_text(title) or f"Chương tại trang {pg}", "start_page": pg})
        source = "toc"
    else:
        for i, pg in enumerate(range(1, n_pages + 1, fallback_every)):
            chapters.append({"title": f"Phần {i + 1} (trang {pg}+)", "start_page": pg})
        source = "fallback"
    for i, c in enumerate(chapters):
        c["id"] = i
    return chapters, source


# --------------------------------------------------------------------------
# Tách câu
# --------------------------------------------------------------------------
_ABBR = {
    "tp", "ts", "ths", "pgs", "gs", "bs", "ks", "cn", "tt", "tr", "nxb", "ql", "đ/c",
    "dr", "mr", "mrs", "ms", "prof", "st", "vs", "no", "etc", "v.v", "tp.hcm",
}
_BOUND = re.compile(r"([.!?…]+[\"”’')\]]*)\s+")
_OPENERS = "\"“‘'([–—-"


def split_sentences(par: str):
    res, start = [], 0
    for m in _BOUND.finditer(par):
        nxt = par[m.end():m.end() + 1]
        if not nxt:
            continue
        if not (nxt.isupper() or nxt.isdigit() or nxt in _OPENERS):
            continue
        term = m.group(1)
        if term == ".":
            words = par[start:m.start(1)].split()
            w = words[-1].strip("\"“‘'([").lower() if words else ""
            if w in _ABBR or (len(w) == 1 and w.isalpha()) or (w.isdigit() and len(w) <= 2):
                continue
        res.append(par[start:m.end(1)].strip())
        start = m.end()
    tail = par[start:].strip()
    if tail:
        res.append(tail)
    return res


def split_long(s: str, max_chars: int):
    """Cắt câu quá dài ở ; : – , gần max_chars nhất, không thì ở khoảng trắng."""
    out = []
    while len(s) > max_chars:
        window = s[:max_chars + 1]
        cut = -1
        for sep in ("; ", ": ", " – ", " — ", ", ", " "):
            idx = window.rfind(sep, int(max_chars * 0.4))
            if idx != -1:
                cut = idx + len(sep.rstrip()) if sep != " " else idx
                break
        if cut <= 0:
            cut = max_chars
        out.append(s[:cut].strip())
        s = s[cut:].strip()
    if s:
        out.append(s)
    return out


def _merge_short(parts, min_chars):
    """Gộp mảnh quá ngắn vào mảnh kề (trong cùng đoạn)."""
    if len(parts) <= 1:
        return parts
    res = []
    for p in parts:
        if res and len(p) < min_chars:
            res[-1] += " " + p
        else:
            res.append(p)
    if len(res) > 1 and len(res[0]) < min_chars:
        res[1] = res[0] + " " + res[1]
        res = res[1:]
    return res


# --------------------------------------------------------------------------
# Hàm chính
# --------------------------------------------------------------------------
def build_units(path, max_chars=220, min_chars=10, ocr=False, ocr_lang="vie",
                dehyphen="keep", chapter_fallback_pages=20, ocr_dpi=300):
    paras, n_pages, info = extract_paragraphs(path, ocr=ocr, ocr_lang=ocr_lang, dehyphen=dehyphen, ocr_dpi=ocr_dpi)
    chapters, chap_source = extract_chapters(path, n_pages, chapter_fallback_pages)

    def chapter_of(page):
        cid = 0
        for c in chapters:
            if c["start_page"] <= page:
                cid = c["id"]
        return cid

    units = []
    total_chars = sum(len(p["text"]) for p in paras)
    for pi, p in enumerate(paras):
        parts = []
        for s in split_sentences(p["text"]):
            parts.extend(split_long(s, max_chars))
        parts = _merge_short(parts, min_chars)
        for s in parts:
            say = normalize_for_tts(s)
            if not is_speakable(say):
                continue
            units.append({
                "i": len(units),
                "p": pi,
                "ch": chapter_of(p["page"]),
                "page": p["page"],
                "hash": unit_hash(say),
                "text": s,
                "say": say,
            })

    avg = total_chars / max(n_pages, 1)
    warnings = []
    if avg < 80:
        warnings.append(
            f"Trung bình chỉ {avg:.0f} ký tự/trang: nhiều khả năng PDF là bản SCAN (không có text). "
            "Cài tesseract rồi chạy lại với OCR=True."
        )
    stats = {
        "pages": n_pages, "paragraphs": len(paras), "units": len(units),
        "unique_units": len({u['hash'] for u in units}), "chars": total_chars,
        "chapter_source": chap_source, "rules": RULES_VERSION, **info,
    }
    return {"units": units, "chapters": chapters, "stats": stats, "warnings": warnings}