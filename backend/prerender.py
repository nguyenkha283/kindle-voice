"""
prerender.py — Tạo trước (pre-render) audio cả chương ra đĩa.

Vì model neural nặng hơn Piper, tổng hợp-khi-bấm-play dễ khựng. Module này:
  1. Nhận danh sách đơn vị đọc (câu/đoạn) đã tách sẵn từ epub_parser.
  2. Gán register cho từng đơn vị (Tagger).
  3. Tổng hợp bằng đúng sắc thái (RegisterBank) và ghi WAV vào cache theo book_id.
  4. Chạy nền trong một luồng, có tiến độ; playback chỉ việc đọc file đã cache.

CÁCH CẮM (trong app.py):
    from registers import RegisterBank
    from tagging   import Tagger
    from prerender import PreRenderer

    bank   = RegisterBank(engine); bank.load()
    tagger = Tagger(use_llm=False)                 # bật True nếu có ANTHROPIC_API_KEY
    prer   = PreRenderer(bank, tagger)

    # khi mở sách/chương:
    prer.enqueue_chapter(book_id, units)           # units = [{"id":.., "text":..}, ...]

    # endpoint phát audio:
    path = prer.get_or_wait(book_id, unit_id, timeout=30)
    return FileResponse(path)                       # WAV đã sẵn trên đĩa
"""

from __future__ import annotations
import os
import threading
import queue
from pathlib import Path
from typing import Callable, Optional

CACHE_ROOT = Path(os.environ.get(
    "AUDIO_CACHE",
    Path(__file__).resolve().parent.parent / "cache" / "audio",
))


class PreRenderer:
    def __init__(self, bank, tagger, cache_root: Path = CACHE_ROOT,
                 workers: int = 1):
        """
        bank    : RegisterBank (đã load)
        tagger  : Tagger
        workers : số luồng tổng hợp. VieNeu nên gọi tuần tự -> để 1 là an toàn.
                  (RegisterBank._infer_wav đã có khóa riêng.)
        """
        self.bank = bank
        self.tagger = tagger
        self.root = Path(cache_root)
        self.root.mkdir(parents=True, exist_ok=True)

        self._q: "queue.Queue[tuple[str, str, str, str]]" = queue.Queue()
        self._inflight: set[tuple[str, str]] = set()
        self._done_events: dict[tuple[str, str], threading.Event] = {}
        self._lock = threading.Lock()
        self.progress: dict[str, dict] = {}          # book_id -> {total, done}

        self._threads = [
            threading.Thread(target=self._worker, daemon=True, name=f"prerender-{i}")
            for i in range(max(1, workers))
        ]
        for t in self._threads:
            t.start()

    # ---- đường dẫn cache ----------------------------------------------------
    def path_for(self, book_id: str, unit_id: str) -> Path:
        safe_book = "".join(c if c.isalnum() or c in "-_" else "_" for c in book_id)
        d = self.root / safe_book
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{unit_id}.wav"

    def is_cached(self, book_id: str, unit_id: str) -> bool:
        p = self.path_for(book_id, unit_id)
        return p.exists() and p.stat().st_size > 44  # >header WAV

    # ---- đưa cả chương vào hàng đợi ----------------------------------------
    def enqueue_chapter(self, book_id: str, units: list[dict],
                        prioritize_first: int = 2) -> None:
        """
        units: [{"id": str, "text": str}, ...] theo đúng thứ tự đọc.
        Gán nhãn cả lô (gộp LLM cho rẻ) rồi xếp hàng. `prioritize_first` đơn vị
        đầu được đẩy lên trước để bấm play là có ngay.
        """
        texts = [u["text"] for u in units]
        ids = [u["id"] for u in units]
        registers = self.tagger.tag_many(texts, ids)  # 1 lần cho cả chương

        with self._lock:
            self.progress[book_id] = {"total": len(units), "done": 0}

        ordered = list(zip(ids, texts, registers))
        # đẩy vài đơn vị đầu lên trước
        head = ordered[:prioritize_first]
        tail = ordered[prioritize_first:]
        for uid, text, reg in head + tail:
            self._submit(book_id, uid, text, reg)

    def _submit(self, book_id: str, unit_id: str, text: str, register: str) -> None:
        key = (book_id, unit_id)
        with self._lock:
            if self.is_cached(book_id, unit_id):
                self._mark_done(book_id)
                return
            if key in self._inflight:
                return
            self._inflight.add(key)
            self._done_events.setdefault(key, threading.Event())
        self._q.put((book_id, unit_id, text, register))

    # ---- lấy file (chờ nếu đang render) ------------------------------------
    def get_or_wait(self, book_id: str, unit_id: str,
                    timeout: float = 30.0) -> Optional[Path]:
        """Trả path WAV đã cache; nếu đang render thì chờ tối đa `timeout` giây."""
        if self.is_cached(book_id, unit_id):
            return self.path_for(book_id, unit_id)
        key = (book_id, unit_id)
        with self._lock:
            ev = self._done_events.get(key)
        if ev is None:
            return None  # chưa từng được xếp hàng
        if ev.wait(timeout) and self.is_cached(book_id, unit_id):
            return self.path_for(book_id, unit_id)
        return None

    def get_progress(self, book_id: str) -> dict:
        with self._lock:
            return dict(self.progress.get(book_id, {"total": 0, "done": 0}))

    # ---- luồng chạy nền -----------------------------------------------------
    def _worker(self) -> None:
        while True:
            book_id, unit_id, text, register = self._q.get()
            key = (book_id, unit_id)
            try:
                if not self.is_cached(book_id, unit_id):
                    wav = self.bank.synthesize(text, register=register)
                    self.path_for(book_id, unit_id).write_bytes(wav)
            except Exception as e:  # noqa: BLE001
                print(f"[prerender] Loi render {book_id}/{unit_id} [{register}]: {e}")
            finally:
                with self._lock:
                    self._inflight.discard(key)
                    ev = self._done_events.get(key)
                self._mark_done(book_id)
                if ev:
                    ev.set()
                self._q.task_done()

    def _mark_done(self, book_id: str) -> None:
        with self._lock:
            p = self.progress.get(book_id)
            if p:
                p["done"] = min(p["done"] + 1, p["total"])
