"""
tagging.py — Gán "register" (sắc thái) cho từng đoạn văn.

Thứ tự ưu tiên khi quyết định sắc thái của một đoạn:
    1. Override thủ công   (bạn tự đánh dấu — chắc chắn nhất)
    2. Marker nội tuyến     (vd đầu đoạn có  ⟦goi_cam⟧ )
    3. Phân loại LLM        (tùy chọn, rẻ, chạy 1 lần lúc pre-render, có cache)
    4. Heuristic đối thoại  (miễn phí: phát hiện lời thoại trong ngoặc kép / gạch đầu dòng)
    5. Mặc định             (trung_tinh)

=> Không bật LLM vẫn chạy tốt: đối thoại nhận bằng heuristic, phần còn lại đọc phẳng.
   Bật LLM thì thêm khả năng nhận "tình cảm / gợi cảm".

CÁCH CẮM:
    from tagging import Tagger
    tagger = Tagger(use_llm=False)                  # hoặc True nếu có ANTHROPIC_API_KEY
    reg = tagger.tag(text)                           # 1 đoạn
    regs = tagger.tag_many([t1, t2, ...])            # nhiều đoạn (LLM sẽ gộp lô)
"""

from __future__ import annotations
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Iterable, Optional

# Danh sách register hợp lệ (khớp registers.py)
VALID_REGISTERS = ("trung_tinh", "doi_thoai", "tinh_cam", "goi_cam")
DEFAULT_REGISTER = "trung_tinh"

# Nơi lưu cache nhãn để không phân loại lại (và không trả tiền LLM lần hai).
CACHE_PATH = Path(os.environ.get(
    "TAG_CACHE",
    Path(__file__).resolve().parent.parent / "cache" / "tags.json",
))

# Marker nội tuyến kiểu ⟦goi_cam⟧ ở đầu đoạn để ép sắc thái.
_MARKER_RE = re.compile(r"^\s*⟦\s*([a-z_]+)\s*⟧\s*")


def strip_marker(text: str) -> tuple[Optional[str], str]:
    """Tách marker nội tuyến (nếu có). Trả (register|None, text_da_bo_marker)."""
    m = _MARKER_RE.match(text or "")
    if not m:
        return None, text
    reg = m.group(1)
    reg = reg if reg in VALID_REGISTERS else None
    return reg, text[m.end():]


# ---- Heuristic: phát hiện đối thoại (miễn phí) -------------------------------
_QUOTE_RE = re.compile(r"[\"“”«»„].+?[\"“”«»„]", re.S)
_DASH_LINE_RE = re.compile(r"^\s*[—–-]\s+\S")  # dòng bắt đầu bằng gạch đầu dòng


def classify_heuristic(text: str) -> Optional[str]:
    """
    Trả 'doi_thoai' nếu đoạn có vẻ là lời thoại, ngược lại None.
    (None = để tầng khác quyết định.)
    """
    t = (text or "").strip()
    if not t:
        return None
    if _DASH_LINE_RE.match(t):
        return "doi_thoai"
    quoted = "".join(_QUOTE_RE.findall(t))
    # Nếu >=40% ký tự nằm trong ngoặc kép -> coi là đối thoại.
    if quoted and len(quoted) / max(len(t), 1) >= 0.40:
        return "doi_thoai"
    return None


# ---- Phân loại bằng LLM (tùy chọn) ------------------------------------------
_LLM_SYSTEM = (
    "Bạn phân loại SẮC THÁI GIỌNG ĐỌC cho từng đoạn văn tiếng Việt trong một cuốn "
    "sách. Chỉ chọn MỘT nhãn cho mỗi đoạn trong: "
    "trung_tinh (kể/tả bình thường), doi_thoai (lời thoại nhân vật), "
    "tinh_cam (xúc động, thân thương, buồn/thương), goi_cam (thân mật, gợi cảm). "
    "Nếu phân vân, chọn trung_tinh."
)


class LLMClassifier:
    """
    Bọc gọi Anthropic API để phân loại theo lô. TÙY CHỌN.
    - Chỉ hoạt động nếu cài `anthropic` và có biến môi trường ANTHROPIC_API_KEY.
    - Thiếu một trong hai -> tự vô hiệu, trả None để rơi về heuristic.
    """

    def __init__(self, model: str = "claude-haiku-4-5-20251001", batch_size: int = 20):
        self.model = model
        self.batch_size = batch_size
        self.client = None
        try:
            import anthropic  # type: ignore
            if os.environ.get("ANTHROPIC_API_KEY"):
                self.client = anthropic.Anthropic()
        except Exception as e:  # noqa: BLE001
            print(f"[tagging] LLM tat (khong co SDK/API key): {e}")

    @property
    def enabled(self) -> bool:
        return self.client is not None

    def classify_batch(self, texts: list[str]) -> list[Optional[str]]:
        """Phân loại một lô đoạn. Phần tử None = không chắc -> để heuristic lo."""
        if not self.enabled or not texts:
            return [None] * len(texts)
        out: list[Optional[str]] = []
        for i in range(0, len(texts), self.batch_size):
            chunk = texts[i:i + self.batch_size]
            out.extend(self._classify_one_call(chunk))
        return out

    def _classify_one_call(self, chunk: list[str]) -> list[Optional[str]]:
        # Đánh số đoạn, yêu cầu model trả JSON {"labels": [...]} để dễ parse.
        numbered = "\n".join(f"[{j}] {t.strip()[:600]}" for j, t in enumerate(chunk))
        prompt = (
            "Phân loại sắc thái cho các đoạn sau. Trả về DUY NHẤT một JSON dạng "
            '{"labels": ["...", ...]} với đúng ' + str(len(chunk)) +
            " nhãn theo thứ tự, mỗi nhãn thuộc "
            "{trung_tinh, doi_thoai, tinh_cam, goi_cam}. Không giải thích.\n\n"
            + numbered
        )
        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=1000,
                system=_LLM_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            txt = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            txt = txt.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
            labels = json.loads(txt).get("labels", [])
            norm = []
            for lb in labels:
                lb = str(lb).strip()
                norm.append(lb if lb in VALID_REGISTERS else None)
            # đệm cho đủ độ dài nếu model trả thiếu
            while len(norm) < len(chunk):
                norm.append(None)
            return norm[:len(chunk)]
        except Exception as e:  # noqa: BLE001
            print(f"[tagging] Loi goi LLM, roi ve heuristic: {e}")
            return [None] * len(chunk)


# ---- Bộ gán nhãn tổng hợp ----------------------------------------------------
def _key(text: str) -> str:
    return hashlib.sha1((text or "").strip().encode("utf-8")).hexdigest()[:16]


class Tagger:
    """Kết hợp override > marker > LLM > heuristic > mặc định, có cache ra đĩa."""

    def __init__(self, use_llm: bool = False,
                 overrides: Optional[dict[str, str]] = None,
                 cache_path: Path = CACHE_PATH):
        self.overrides = overrides or {}          # {unit_id: register}
        self.cache_path = Path(cache_path)
        self._cache: dict[str, str] = self._load_cache()
        self.llm = LLMClassifier() if use_llm else None

    # -- cache --
    def _load_cache(self) -> dict[str, str]:
        try:
            return json.loads(self.cache_path.read_text("utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    def _save_cache(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(
                json.dumps(self._cache, ensure_ascii=False), "utf-8")
        except Exception as e:  # noqa: BLE001
            print(f"[tagging] Khong luu duoc cache: {e}")

    # -- một đoạn --
    def tag(self, text: str, unit_id: Optional[str] = None) -> str:
        # 1) override thủ công
        if unit_id and unit_id in self.overrides:
            return self.overrides[unit_id]
        # 2) marker nội tuyến
        marker, body = strip_marker(text)
        if marker:
            return marker
        # cache
        k = _key(body)
        if k in self._cache:
            return self._cache[k]
        # 4) heuristic (rẻ, làm trước để tiết kiệm LLM)
        h = classify_heuristic(body)
        reg = h
        # 3) LLM nếu bật và heuristic chưa quyết
        if reg is None and self.llm and self.llm.enabled:
            reg = self.llm.classify_batch([body])[0]
        reg = reg or DEFAULT_REGISTER
        self._cache[k] = reg
        return reg

    # -- nhiều đoạn (gộp lô LLM cho rẻ) --
    def tag_many(self, texts: Iterable[str],
                 unit_ids: Optional[list[str]] = None) -> list[str]:
        texts = list(texts)
        ids = unit_ids or [None] * len(texts)
        result: list[Optional[str]] = [None] * len(texts)
        pending_idx: list[int] = []
        pending_txt: list[str] = []

        for i, (t, uid) in enumerate(zip(texts, ids)):
            if uid and uid in self.overrides:
                result[i] = self.overrides[uid]
                continue
            marker, body = strip_marker(t)
            if marker:
                result[i] = marker
                continue
            k = _key(body)
            if k in self._cache:
                result[i] = self._cache[k]
                continue
            h = classify_heuristic(body)
            if h is not None:
                result[i] = h
                self._cache[k] = h
                continue
            # còn lại -> gửi LLM (nếu có)
            pending_idx.append(i)
            pending_txt.append(body)

        if pending_txt and self.llm and self.llm.enabled:
            labels = self.llm.classify_batch(pending_txt)
        else:
            labels = [None] * len(pending_txt)

        for idx, lb, body in zip(pending_idx, labels, pending_txt):
            reg = lb or DEFAULT_REGISTER
            result[idx] = reg
            self._cache[_key(body)] = reg

        self._save_cache()
        return [r or DEFAULT_REGISTER for r in result]
