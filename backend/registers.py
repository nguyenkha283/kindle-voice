"""
registers.py — Ngân hàng "register" (sắc thái giọng) cho trình đọc.

Cùng MỘT giọng của bạn, thu ở nhiều sắc thái (kể chuyện phẳng, đối thoại, tình cảm,
gợi cảm). Mỗi sắc thái là một clip mẫu nạp vào VieNeu qua add_voice; app chọn sắc
thái khớp từng đoạn khi đọc.

THIẾT KẾ "CHỜ FILE":
- Thả WAV vào references/registers/ theo tên trong REGISTER_SPECS.
- File nào CÓ thì register đó bật; thiếu thì fallback theo chuỗi dự phòng, cuối cùng
  về giọng mặc định của engine. => Chưa có file nào -> app chạy y như cũ.

Tính năng:
- Cache audio RA ĐĨA theo hash(text|register) -> đọc lại tức thì, bền qua khởi động.
- Chèn thêm khoảng nghỉ cuối đơn vị theo pause_scale (gợi cảm/tình cảm nghỉ dài hơn).
"""

from __future__ import annotations
import hashlib
import io
import os
import tempfile
import unicodedata
import wave
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Optional

REGISTER_DIR = Path(os.environ.get(
    "REGISTER_DIR",
    Path(__file__).resolve().parent.parent / "references" / "registers",
))
AUDIO_CACHE_DIR = Path(os.environ.get(
    "REG_AUDIO_CACHE",
    Path(__file__).resolve().parent.parent / "cache" / "audio_reg",
))

# Tên thuộc tính chứa đối tượng Vieneu trong engine (sửa nếu khác).
_TTS_ATTR = "tts"
DEFAULT_STYLE = "doc_truyen"
# Khoảng nghỉ "gốc" (giây) để nhân với (pause_scale - 1) khi chèn lặng cuối đơn vị.
_BASE_PAUSE = 0.40


@dataclass
class RegisterSpec:
    name: str
    filename: str
    label: str
    temperature: float
    pause_scale: float = 1.0
    fallback: tuple[str, ...] = ()


# 4 register lõi (khớp file hướng dẫn thu clip). Temp thấp = ổn định, cao = biểu cảm;
# vì đã neo giọng bằng clip mẫu nên tăng temp không đổi danh tính, chỉ thêm biểu cảm.
REGISTER_SPECS: dict[str, RegisterSpec] = {
    "trung_tinh": RegisterSpec("trung_tinh", "trung_tinh.wav", "Kể chuyện",
                               temperature=0.70, pause_scale=1.0),
    "doi_thoai":  RegisterSpec("doi_thoai",  "doi_thoai.wav",  "Đối thoại",
                               temperature=0.78, pause_scale=0.95,
                               fallback=("trung_tinh",)),
    "tinh_cam":   RegisterSpec("tinh_cam",   "tinh_cam.wav",   "Tình cảm",
                               temperature=0.80, pause_scale=1.15,
                               fallback=("trung_tinh",)),
    "goi_cam":    RegisterSpec("goi_cam",    "goi_cam.wav",    "Gợi cảm",
                               temperature=0.85, pause_scale=1.30,
                               fallback=("tinh_cam", "trung_tinh")),
}
DEFAULT_REGISTER = "trung_tinh"


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.strip().lower()


def _audio_key(text: str, register: str) -> str:
    raw = f"{register}|{(text or '').strip()}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()


def _append_silence(wav_bytes: bytes, seconds: float) -> bytes:
    """Nối thêm `seconds` giây khoảng lặng vào cuối một WAV (khớp đúng thông số)."""
    if seconds <= 0 or len(wav_bytes) <= 44:
        return wav_bytes
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as r:
            nch, sw, fr = r.getnchannels(), r.getsampwidth(), r.getframerate()
            frames = r.readframes(r.getnframes())
        pad = b"\x00" * int(fr * seconds) * nch * sw
        out = io.BytesIO()
        with wave.open(out, "wb") as w:
            w.setnchannels(nch)
            w.setsampwidth(sw)
            w.setframerate(fr)
            w.writeframes(frames + pad)
        return out.getvalue()
    except Exception:
        return wav_bytes  # lỗi định dạng -> trả nguyên


class RegisterBank:
    def __init__(self, engine, register_dir: Path = REGISTER_DIR,
                 audio_cache_dir: Path = AUDIO_CACHE_DIR):
        self.engine = engine
        self.tts = getattr(engine, _TTS_ATTR, None)
        self.dir = Path(register_dir)
        self.cache_dir = Path(audio_cache_dir)
        self._lock = Lock()
        self._voice_ids: dict[str, str] = {}
        self.loaded: list[str] = []

    # ---- nạp clip ----------------------------------------------------------
    def load(self) -> list[str]:
        if self.tts is None:
            print("[registers] CANH BAO: khong tim thay engine.tts -> dung giong mac dinh.")
            return []
        self.dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        loaded: list[str] = []
        for spec in REGISTER_SPECS.values():
            path = self.dir / spec.filename
            if not path.exists():
                continue  # CHỜ FILE
            try:
                voice_name = f"__reg_{spec.name}__"
                adder = getattr(self.engine, "add_named_voice", None)
                if callable(adder):
                    adder(voice_name, str(path))      # có báo lỗi torch thân thiện
                else:
                    self.tts.add_voice(voice_name, str(path))
                self._voice_ids[spec.name] = voice_name
                loaded.append(spec.name)
                print(f"[registers] Da nap '{spec.label}' <- {path.name}")
            except Exception as e:  # noqa: BLE001
                print(f"[registers] Loi nap '{spec.name}' ({path.name}): {e}")
        self.loaded = loaded
        print(f"[registers] San sang: {loaded}" if loaded
              else "[registers] Chua co clip nao -> dung giong mac dinh cua engine.")
        return loaded

    # ---- phân giải register -> voice_id (fallback) -------------------------
    def resolve(self, register: Optional[str]) -> tuple[Optional[str], RegisterSpec]:
        name = register or DEFAULT_REGISTER
        if name not in REGISTER_SPECS:
            for k in REGISTER_SPECS:
                if _norm(k) == _norm(name):
                    name = k
                    break
        spec = REGISTER_SPECS.get(name, REGISTER_SPECS[DEFAULT_REGISTER])
        for cand in (spec.name, *spec.fallback, DEFAULT_REGISTER):
            vid = self._voice_ids.get(cand)
            if vid:
                return vid, REGISTER_SPECS[cand]
        return None, spec  # chưa có clip -> engine tự dùng giọng mặc định

    def available(self) -> list[str]:
        return list(self.loaded)

    # ---- tổng hợp (có cache đĩa + khoảng nghỉ) -----------------------------
    def synthesize(self, text: str, register: Optional[str] = None) -> bytes:
        text = (text or "").strip()
        if not text:
            raise ValueError("Văn bản rỗng")
        voice_id, spec = self.resolve(register)

        ckey = _audio_key(text, spec.name)
        cached = self._disk_get(ckey)
        if cached is not None:
            return cached

        wav = self._infer_wav(text, voice_id, spec.temperature)
        if spec.pause_scale and spec.pause_scale > 1.0:
            wav = _append_silence(wav, _BASE_PAUSE * (spec.pause_scale - 1.0))
        self._disk_put(ckey, wav)
        return wav

    # ---- cache đĩa ----------------------------------------------------------
    def _disk_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.wav"

    def _disk_get(self, key: str) -> Optional[bytes]:
        p = self._disk_path(key)
        try:
            if p.exists() and p.stat().st_size > 44:
                return p.read_bytes()
        except OSError:
            pass
        return None

    def _disk_put(self, key: str, wav: bytes) -> None:
        if len(wav) <= 44:
            return
        p = self._disk_path(key)
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_bytes(wav)
            tmp.replace(p)  # ghi nguyên tử
        except OSError as e:
            print(f"[registers] Khong ghi duoc cache {key}: {e}")

    # ---- cầu nối tới VieNeu -------------------------------------------------
    def _infer_wav(self, text: str, voice_id: Optional[str],
                   temperature: Optional[float]) -> bytes:
        hook = getattr(self.engine, "synth_register", None)
        if callable(hook):
            return hook(text, voice_id, temperature)
        # Dự phòng: gọi thẳng tts (khi engine không có synth_register).
        kw = {"style": DEFAULT_STYLE}
        if voice_id:
            kw["voice"] = voice_id
        if temperature is not None:
            kw["temperature"] = temperature
        with self._lock:
            audio = self.tts.infer(text, **kw)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp = f.name
            try:
                self.tts.save(audio, tmp)
                with open(tmp, "rb") as fh:
                    return fh.read()
            finally:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
