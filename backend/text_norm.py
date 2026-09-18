"""text_norm.py — Chuẩn hoá văn bản NGAY TRƯỚC KHI đưa vào TTS.

Đặt ở tầng phát âm (engine) chứ KHÔNG ở parser: nhờ vậy màn hình vẫn hiển thị
nguyên văn ("I", "II", "Chương III"...) trong khi phần đọc được chuẩn hoá cho
đúng và tránh model sinh âm rác.

Xử lý hai vấn đề chính:
  1) Đầu mục đánh số La Mã (I, II, "Chương IV"...) đọc thành số đếm tiếng Việt
     ("một", "hai", "Chương bốn").
  2) Ký tự lạ / không đọc được (ký hiệu, mũi tên, emoji, dấu chú thích sót lại)
     bị loại bỏ để neural TTS không "babble" ra đoạn vô nghĩa không có trong sách.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

# --------------------------------------------------------------------------- #
# 1) Số La Mã -> chữ tiếng Việt                                                #
# --------------------------------------------------------------------------- #

# Số La Mã HỢP LỆ (in hoa), 1..3999. Dùng để tránh nhận nhầm chữ thường gặp.
_ROMAN_RE = re.compile(
    r"^M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$"
)

# Từ khoá đứng trước số thứ tự trong đầu mục (sau các từ này, số La Mã chắc chắn
# là số thứ tự nên chuyển an toàn). So khớp không phân biệt hoa/thường.
_INDEX_WORDS = (
    "chương", "phần", "mục", "hồi", "bài", "tập", "quyển", "kỳ", "chuyện",
    "chapter", "part", "book", "section", "act", "canto",
)
_KEYWORD_ROMAN_RE = re.compile(
    r"\b(" + "|".join(_INDEX_WORDS) + r")\s+([IVXLCDM]+)\b",
    re.IGNORECASE,
)
# Số La Mã đứng ĐẦU chuỗi, theo sau là dấu phân cách hoặc hết chuỗi:
#   "I", "II.", "III -", "IV: Mở đầu", "(V)"...
_LEADING_ROMAN_RE = re.compile(
    r"^\s*[(\[]?\s*([IVXLCDM]+)\s*[)\]]?\s*(?=[.)\]:\-—–]|\s|$)"
)

_ONES = ["", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]
_TENS_UNIT = {1: "mốt", 4: "tư", 5: "lăm"}  # biến âm ở hàng đơn vị khi có hàng chục


def roman_to_int(s: str) -> Optional[int]:
    """Chuyển chuỗi số La Mã (in hoa) -> int, hoặc None nếu không hợp lệ."""
    s = (s or "").upper()
    if not s or not _ROMAN_RE.match(s):
        return None
    vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total, prev = 0, 0
    for ch in reversed(s):
        v = vals[ch]
        total += -v if v < prev else v
        prev = v
    return total


def _under_hundred(n: int) -> str:
    """0..99 -> chữ (dùng cho ghép hàng trăm)."""
    if n < 10:
        return _ONES[n]
    tens, unit = divmod(n, 10)
    head = "mười" if tens == 1 else f"{_ONES[tens]} mươi"
    if unit == 0:
        return head
    return f"{head} {_TENS_UNIT.get(unit, _ONES[unit])}"


def int_to_vietnamese(n: int) -> str:
    """Đọc số nguyên dương -> chữ tiếng Việt (đủ dùng cho đầu mục, 1..3999)."""
    if n <= 0:
        return str(n)
    if n < 100:
        return _under_hundred(n)
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        out = f"{_ONES[hundreds]} trăm"
        if rest == 0:
            return out
        if rest < 10:                     # "linh" cho hàng chục trống
            return f"{out} linh {_ONES[rest]}"
        return f"{out} {_under_hundred(rest)}"
    thousands, rest = divmod(n, 1000)
    out = f"{int_to_vietnamese(thousands)} nghìn"
    if rest == 0:
        return out
    if rest < 100:
        return f"{out} không trăm {_under_hundred(rest)}" if rest >= 10 \
            else f"{out} không trăm linh {_ONES[rest]}"
    return f"{out} {int_to_vietnamese(rest)}"


def _roman_word(token: str) -> Optional[str]:
    n = roman_to_int(token)
    return int_to_vietnamese(n) if n else None


def _convert_roman_headings(text: str) -> str:
    """Chuyển số La Mã trong đầu mục -> chữ tiếng Việt (giữ nguyên phần còn lại)."""
    # a) "Chương IV" -> "Chương bốn"
    def _kw(m: re.Match) -> str:
        word = _roman_word(m.group(2))
        return f"{m.group(1)} {word}" if word else m.group(0)

    text = _KEYWORD_ROMAN_RE.sub(_kw, text)

    # b) Số La Mã đứng đầu chuỗi ("I", "II.", "III - ...") -> chữ.
    m = _LEADING_ROMAN_RE.match(text)
    if m:
        word = _roman_word(m.group(1))
        if word:
            text = text[:m.start(1)] + word + text[m.end(1):]
    return text


# --------------------------------------------------------------------------- #
# 2) Lọc ký tự lạ (chống "babble" của neural TTS)                              #
# --------------------------------------------------------------------------- #

# Dấu câu / ký hiệu được PHÉP giữ lại (đọc được hoặc ảnh hưởng ngắt nghỉ).
_ALLOWED_PUNCT = set(".,;:!?…\"'`“”‘’«»()[]-—–/%")
# Khoảng trắng gộp về một dấu cách.
_WS_RE = re.compile(r"\s+")
# Có ít nhất một chữ cái hoặc chữ số -> mới đáng đọc.
_HAS_ALNUM_RE = re.compile(r"[^\W_]", re.UNICODE)


def _strip_exotic(text: str) -> str:
    """Bỏ ký tự không phải chữ/số/khoảng trắng/dấu-câu-cho-phép.

    Chữ có dấu tiếng Việt (và mọi chữ cái Unicode) là `isalpha()` nên được giữ;
    emoji, mũi tên, ký hiệu toán, box-drawing, ký tự điều khiển... bị loại.
    """
    out = []
    for ch in text:
        if ch.isalpha() or ch.isdigit() or ch.isspace() or ch in _ALLOWED_PUNCT:
            out.append(ch)
        # ký tự khác: bỏ (thay bằng khoảng trắng để không dính chữ)
        else:
            out.append(" ")
    return "".join(out)


def is_speakable(text: str) -> bool:
    """Sau chuẩn hoá, còn ít nhất một chữ cái/chữ số -> mới nên đưa vào TTS."""
    return bool(_HAS_ALNUM_RE.search(text or ""))


def normalize_for_tts(text: str) -> str:
    """Chuẩn hoá một đơn vị văn bản trước khi tổng hợp giọng.

    Trả về chuỗi đã: chuẩn hoá Unicode (NFC), chuyển số La Mã ở đầu mục thành
    chữ tiếng Việt, loại ký tự lạ và gộp khoảng trắng. Có thể trả chuỗi rỗng
    (khi đầu vào chỉ gồm ký hiệu) — gọi kèm `is_speakable` để bỏ qua khi rỗng.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = _convert_roman_headings(text)
    text = _strip_exotic(text)
    text = _WS_RE.sub(" ", text).strip()
    return text
