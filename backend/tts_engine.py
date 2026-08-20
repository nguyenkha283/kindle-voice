"""Bộ đọc giọng offline dùng Piper (mô hình ONNX, chạy CPU, không cần mạng).

Hỗ trợ 2 cách chạy Piper để dễ cài trên nhiều máy:
  1) Gói Python `piper-tts`  (ưu tiên — nạp mô hình vào RAM, nhanh).
  2) Binary `piper`          (dự phòng — nếu không cài được gói Python).

- Nạp/khởi tạo 1 lần lúc chạy, tổng hợp từng câu -> WAV bytes.
- Cache câu đã đọc để đọc lại tức thì.
- Nếu chưa có mô hình / chưa cài Piper, engine "chưa sẵn sàng" và API trả 503
  kèm hướng dẫn (xem README).
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tempfile
import wave
from collections import OrderedDict
from pathlib import Path
from threading import Lock
from typing import Optional

# ---------------------------------------------------------------------------
# Ngắt nghỉ theo dấu câu: độ dài khoảng lặng (giây) chèn sau mỗi loại dấu.
# Chỉnh các số này để tăng/giảm độ "thở" khi đọc.
# ---------------------------------------------------------------------------
PAUSE = {
    "comma": 0.18,      # ,
    "clause": 0.30,     # ; :
    "ellipsis": 0.45,   # … ...
    "dash": 0.25,       # — –
    "sentence": 0.42,   # . ! ?
    "tail": 0.15,       # vế cuối không có dấu
}

# Dấu ngắt, chỉ tính là ngắt khi phía sau là khoảng trắng / hết chuỗi
# (nhờ vậy KHÔNG cắt nhầm số thập phân "1,5" hay "3.14").
_BREAK = re.compile(
    r'(\.\.\.|…|[,;:—–]|[.!?。！？])(?=["”\'’)\]]*(?:\s|$))'
)


def _pause_for(punct: Optional[str]) -> float:
    if punct is None:
        return PAUSE["tail"]
    if punct == "..." or punct == "…":
        return PAUSE["ellipsis"]
    if punct in ".!?。！？":
        return PAUSE["sentence"]
    if punct in ";:":
        return PAUSE["clause"]
    if punct in ",，":
        return PAUSE["comma"]
    if punct in "—–":
        return PAUSE["dash"]
    return PAUSE["comma"]


def _split_phrases(sentence: str) -> list[tuple[str, float]]:
    """Tách câu thành các vế [(văn bản kèm dấu, khoảng lặng sau vế)]."""
    out: list[tuple[str, float]] = []
    last = 0
    for m in _BREAK.finditer(sentence):
        phrase = sentence[last:m.end()].strip()
        if phrase:
            out.append((phrase, _pause_for(m.group(1))))
        last = m.end()
    tail = sentence[last:].strip()
    if tail:
        out.append((tail, _pause_for(None)))
    return out


def _wav_to_pcm(wav_bytes: bytes):
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        return (
            w.readframes(w.getnframes()),
            w.getframerate(), w.getsampwidth(), w.getnchannels(),
        )


def _build_wav(pcm: bytes, rate: int, width: int, ch: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _silence(seconds: float, rate: int, width: int, ch: int) -> bytes:
    return b"\x00" * (int(seconds * rate) * width * ch)


class TTSEngine:
    def __init__(self, model_path: Optional[Path], cache_size: int = 512):
        self.model_path = model_path
        self.mode: Optional[str] = None      # "python" | "binary"
        self.voice = None                    # doi tuong PiperVoice (mode python)
        self.binary: Optional[str] = None    # duong dan binary (mode binary)
        self.config_path: Optional[Path] = None
        self.voice_name: Optional[str] = None
        self.error: Optional[str] = None
        self._lock = Lock()
        self._cache: "OrderedDict[str, bytes]" = OrderedDict()
        self._cache_size = cache_size
        self._init()

    # ------------------------------------------------------------------ init
    def _init(self) -> None:
        if not self.model_path or not self.model_path.exists():
            self.error = "Chua tim thay mo hinh giong (.onnx) trong thu muc voices/. Xem README."
            return

        cfg = Path(str(self.model_path) + ".json")
        if not cfg.exists():
            cfg = self.model_path.with_suffix(".onnx.json")
        self.config_path = cfg if cfg.exists() else None
        self.voice_name = self.model_path.name

        if self._load_python():
            self.mode = "python"
            self.error = None
            return

        py_err = self.error
        if self._find_binary():
            self.mode = "binary"
            self.error = None
            return

        self.error = (
            "Chua dung duoc Piper. Cai goi `pip install piper-tts` "
            f"hoac dat binary `piper` vao PATH. (Chi tiet: {py_err})"
        )

    def _load_python(self) -> bool:
        try:
            try:
                from piper.voice import PiperVoice  # piper-tts >= 1.2
            except Exception:
                from piper import PiperVoice          # ban cu hon
            self.voice = PiperVoice.load(
                str(self.model_path),
                config_path=str(self.config_path) if self.config_path else None,
            )
            return True
        except Exception as e:  # noqa: BLE001
            self.error = f"goi piper-tts loi: {e}"
            self.voice = None
            return False

    def _find_binary(self) -> bool:
        cand = os.environ.get("PIPER_BIN") or shutil.which("piper")
        if not cand:
            local = self.model_path.parent / ("piper.exe" if os.name == "nt" else "piper")
            if local.exists():
                cand = str(local)
        if cand and Path(cand).exists():
            self.binary = cand
            return True
        return False

    @property
    def ready(self) -> bool:
        return self.mode is not None

    # Piper không hỗ trợ đổi giọng lúc chạy (đổi bằng file model trong voices/).
    def list_voices(self) -> list:
        return []

    def set_voice(self, voice_id: str) -> bool:
        return False

    def set_blend(self, preset_id) -> bool:
        return False

    # ------------------------------------------------------------- synthesize
    def synthesize(self, text: str) -> bytes:
        if not self.ready:
            raise RuntimeError(self.error or "TTS chua san sang")
        key = text.strip()
        if not key:
            raise ValueError("Van ban rong")

        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return cached

        wav = self._render_with_pauses(key)
        if len(wav) <= 44:
            raise RuntimeError("Piper khong tao duoc audio (kiem tra mo hinh/giong).")

        with self._lock:
            self._cache[key] = wav
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return wav

    def _render_with_pauses(self, sentence: str) -> bytes:
        """Đọc từng vế rồi ghép lại, chèn khoảng lặng theo dấu ngắt."""
        phrases = _split_phrases(sentence) or [(sentence, PAUSE["sentence"])]
        rendered: list[tuple[bytes, float]] = []
        rate = width = ch = None
        for phrase, pause in phrases:
            wav = self._run_python(phrase) if self.mode == "python" else self._run_binary(phrase)
            pcm, rate, width, ch = _wav_to_pcm(wav)
            rendered.append((pcm, pause))
        if rate is None:
            raise RuntimeError("Khong tong hop duoc ve nao.")
        out = bytearray()
        for pcm, pause in rendered:
            out += pcm
            if pause > 0:
                out += _silence(pause, rate, width, ch)
        return _build_wav(bytes(out), rate, width, ch)

    # -------- mode: python -------------------------------------------------
    def _run_python(self, text: str) -> bytes:
        v = self.voice
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav_file:
            if hasattr(v, "synthesize_wav"):
                # piper-tts >= 1.3 (OHF-Voice/piper1-gpl): ghi thang ra wave
                v.synthesize_wav(text, wav_file)
            else:
                # piper-tts 1.2.x (ban cu): synthesize(text, wav_file)
                result = v.synthesize(text, wav_file)
                if buf.tell() == 0 and result is not None:
                    self._write_stream(result, wav_file)
        return buf.getvalue()

    def _write_stream(self, chunks, wav_file: "wave.Wave_write") -> None:
        sr = 22050
        cfg = getattr(self.voice, "config", None)
        if cfg is not None:
            sr = getattr(cfg, "sample_rate", sr)
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sr)
        for chunk in chunks:
            audio = getattr(chunk, "audio_int16_bytes", None)
            if audio is None and isinstance(chunk, (bytes, bytearray)):
                audio = bytes(chunk)
            if audio:
                wav_file.writeframes(audio)

    # -------- mode: binary -------------------------------------------------
    def _run_binary(self, text: str) -> bytes:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.wav"
            cmd = [self.binary, "-m", str(self.model_path), "-f", str(out)]
            if self.config_path:
                cmd += ["-c", str(self.config_path)]
            proc = subprocess.run(
                cmd, input=text.encode("utf-8"),
                capture_output=True, timeout=120,
            )
            if proc.returncode != 0 or not out.exists():
                raise RuntimeError(
                    "piper binary loi: " + proc.stderr.decode("utf-8", "ignore")[:300]
                )
            return out.read_bytes()

    # ------------------------------------------------------------- status
    def status(self) -> dict:
        return {
            "ready": self.ready,
            "mode": self.mode,
            "voice": self.voice_name,
            "error": self.error,
        }
