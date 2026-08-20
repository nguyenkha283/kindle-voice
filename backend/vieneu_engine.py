"""Bộ đọc giọng offline dùng VieNeu-TTS v3 Turbo (tiếng Việt, 48kHz).

- Chạy trên CPU qua ONNX Runtime (không cần GPU), hoàn toàn offline sau khi
  đã tải model lần đầu.
- Phát âm tiếng Việt tự nhiên/chuẩn hơn Piper; tự lo ngắt nghỉ & biểu cảm nên
  KHÔNG cần chèn khoảng lặng thủ công như engine Piper.
- Cùng giao diện với TTSEngine (ready / status / synthesize) để app dùng chung.

Cấu hình qua biến môi trường:
  VIENEU_VOICE      tên/nhãn giọng preset (mặc định: giọng đầu tiên có sẵn)
  VIENEU_PRECISION  int8 (mặc định, nhanh/nhẹ) hoặc fp32 (nét hơn, chậm hơn)
"""
from __future__ import annotations

import io
import os
import re
import tempfile
import unicodedata
import wave
from collections import OrderedDict
from pathlib import Path
from threading import Lock
from typing import Optional


def _norm_key(s: str) -> str:
    """Chuẩn hoá tên giọng để so khớp: NFC + bỏ khoảng trắng + thường hoá."""
    return unicodedata.normalize("NFC", (s or "")).replace(" ", "").strip().lower()

# Bất kỳ chữ cái nào (kể cả có dấu tiếng Việt)
_HAS_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)
_TRAIL_BREAK = re.compile(r"[\s,;:—–]+$")


def _is_trivial(text: str) -> bool:
    """Đoạn không có chữ cái (chỉ số/ký hiệu) -> không nên đưa vào TTS."""
    return not _HAS_LETTER.search(text or "")


def _prep_text(text: str) -> str:
    """Đảm bảo đoạn kết thúc bằng dấu câu — giúp model không sinh audio rỗng."""
    t = (text or "").strip()
    if not t:
        return t
    t = _TRAIL_BREAK.sub("", t)          # bỏ dấu phẩy/hai chấm... ở cuối
    if t and t[-1] not in ".!?…":
        t += "."                          # thêm dấu chấm nếu chưa có dấu kết
    return t


def _silence_wav(seconds: float = 0.12, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


class VieNeuEngine:
    def __init__(self, voice: Optional[str] = None,
                 precision: Optional[str] = None, cache_size: int = 512):
        self.tts = None
        self.voice_id: Optional[str] = None
        self.voice_label: Optional[str] = None
        self.voices: list[tuple] = []
        self.ref_audio: Optional[str] = None     # đường dẫn file mẫu (nhân bản giọng)
        self.cloned = False                      # đang dùng giọng nhân bản?
        self._clone_name = "__cloned__"          # tên preset nội bộ cho giọng nhân bản
        self.blend_from: Optional[str] = None    # mượn "ngữ điệu" (codes) từ preset này
        self._blend_voice = None                 # dict = speaker_emb(clone) + codes(preset)
        self._blend_failed = False               # ghép chéo sinh rỗng -> đã lùi về clone
        self.error: Optional[str] = None
        self.mode = "vieneu"
        self._lock = Lock()
        self._synth_lock = Lock()                # nối tiếp việc tạo giọng
        self._cache: "OrderedDict[str, bytes]" = OrderedDict()
        self._cache_size = cache_size
        self._want_voice = voice or os.environ.get("VIENEU_VOICE")
        self._precision = precision or os.environ.get("VIENEU_PRECISION", "int8")
        _t = os.environ.get("VIENEU_TEMPERATURE")
        # Mặc định 0.8 — mức ổn định nhất cho v3 Turbo, giảm hiện tượng "trôi giọng"
        # (mỗi câu bốc thăm lại chất giọng). Hạ 0.7/0.6 nếu vẫn muốn ổn định hơn nữa;
        # tăng >0.8 sẽ biểu cảm hơn nhưng dễ đổi giọng giữa các câu.
        self.temperature = float(_t) if _t else 0.8
        self._load()

    # ------------------------------------------------------------------ load
    def _load(self) -> None:
        try:
            from vieneu import Vieneu
        except Exception as e:  # noqa: BLE001
            self.error = f"Chua cai vieneu. Chay: pip install vieneu ({e})"
            return
        try:
            # Lần đầu sẽ tải model (~vài trăm MB) rồi cache lại cho các lần sau.
            self.tts = Vieneu(
                mode="v3turbo",
                precision=self._precision,
                device=os.environ.get("VIENEU_DEVICE", "auto"),
            )
            try:
                voices = self.tts.list_preset_voices()  # [(label, id), ...]
            except Exception:
                voices = []
            # Chỉ dùng một giọng duy nhất (mặc định Thục Đoan). So khớp theo chuẩn
            # NFC + bỏ hoa/thường/khoảng trắng để không lệch do dấu tiếng Việt.
            only = os.environ.get("VIENEU_ONLY")
            if only is None:
                only = "Thục Đoan"
            if only:
                key = _norm_key(only)
                # Khớp cả voice_id LẪN label: id thật có thể là slug khác tên hiển
                # thị (vd id="thuc_doan" nhưng label="Thục Đoan"). Trước đây chỉ khớp
                # id nên khi trượt sẽ âm thầm giữ cả danh sách -> giọng bị đổi lung tung.
                picked = [(lab, vid) for (lab, vid) in voices
                          if _norm_key(vid) == key or _norm_key(lab) == key]
                if picked:
                    voices = picked
                elif voices:
                    print(f"[VieNeu] CANH BAO: khong tim thay giong '{only}'. Dang giu "
                          f"ca danh sach ({len(voices)} giong) -> giong co the KHONG co "
                          f"dinh. Cac giong san co: {[v[0] for v in voices]}")
            self.voices = voices
            self._select_voice(voices)
            # Chẩn đoán: in giọng thực sự đang dùng + số giọng sau lọc + temperature.
            # Nếu 'so giong' > 1 nghĩa là bộ lọc trượt (xem cảnh báo ở trên).
            print(f"[VieNeu] Giong dang dung: {self.voice_label} / {self.voice_id} "
                  f"| so giong sau loc = {len(self.voices)} "
                  f"| temperature = {self.temperature}")
        except Exception as e:  # noqa: BLE001
            self.tts = None
            self.error = f"Khong nap duoc VieNeu (kiem tra mang khi tai model): {e}"

    def _select_voice(self, voices) -> None:
        ids = [v[1] for v in voices] if voices else []
        by_label = {v[0]: v[1] for v in voices} if voices else {}
        want = self._want_voice
        if want:
            if want in ids:
                self.voice_id = want
            elif want in by_label:
                self.voice_id = by_label[want]
        if not self.voice_id and ids:
            self.voice_id = ids[0]          # mặc định: giọng preset đầu tiên
        for lab, vid in voices:
            if vid == self.voice_id:
                self.voice_label = lab
                break

    @property
    def ready(self) -> bool:
        return self.tts is not None

    # ------------------------------------------------------------- voices
    def list_voices(self) -> list[dict]:
        return [{"id": vid, "label": lab} for lab, vid in self.voices]

    def set_voice(self, voice_id: str) -> bool:
        ids = [vid for _, vid in self.voices]
        if voice_id not in ids:
            return False
        self.voice_id = voice_id
        self.ref_audio = None                 # đổi sang giọng preset -> tắt nhân bản
        self.cloned = False
        for lab, vid in self.voices:
            if vid == voice_id:
                self.voice_label = lab
                break
        self._rebuild_blend()
        with self._lock:
            self._cache.clear()
        return True

    # ------------------------------------------------- blend (mượn ngữ điệu)
    def _rebuild_blend(self) -> None:
        """Dựng voice dict = speaker_emb của giọng clone + codes của preset mượn."""
        self._blend_voice = None
        self._blend_failed = False
        if self.cloned and self.blend_from:
            try:
                cloned = self.tts.get_preset_voice(self._clone_name)
                preset = self.tts.get_preset_voice(self.blend_from)
                self._blend_voice = {
                    "speaker_emb": cloned["speaker_emb"],
                    "codes": preset.get("codes"),
                }
            except Exception:
                self._blend_voice = None

    def set_blend(self, preset_id: Optional[str]) -> bool:
        if preset_id:
            ids = [vid for _, vid in self.voices]
            if preset_id not in ids:
                return False
            self.blend_from = preset_id
        else:
            self.blend_from = None
        self._rebuild_blend()
        with self._lock:
            self._cache.clear()
        return True

    # ------------------------------------------------------------- clone
    def set_reference(self, path: str, denoise: Optional[bool] = None,
                      use_ref_codes: Optional[bool] = None) -> bool:
        if not path or not os.path.exists(path):
            return False
        if denoise is None:
            denoise = os.environ.get("VIENEU_DENOISE", "1") not in ("0", "false", "False")
        if use_ref_codes is None:
            use_ref_codes = os.environ.get("VIENEU_REF_CODES", "1") not in ("0", "false", "False")
        # Tính trước đặc trưng giọng MỘT LẦN (giải nhiễu + embedding) rồi đăng ký
        # thành preset nội bộ -> mỗi câu sau đọc nhanh, không xử lý lại file mẫu.
        try:
            try:
                self.tts.remove_voice(self._clone_name, save=False)
            except Exception:
                pass
            self.tts.add_voice(self._clone_name, path,
                               denoise=denoise, use_ref_codes=use_ref_codes)
        except ModuleNotFoundError as e:
            raise RuntimeError(
                "Nhân bản giọng cần cài thêm torch. Chạy: "
                "pip install torch torchaudio --index-url "
                "https://download.pytorch.org/whl/cpu"
            ) from e
        self.ref_audio = path
        self.cloned = True
        self.voice_id = self._clone_name
        self._rebuild_blend()
        with self._lock:
            self._cache.clear()
        return True

    def clear_reference(self) -> None:
        self.ref_audio = None
        self.cloned = False
        ids = [vid for _, vid in self.voices]
        if ids:
            self.voice_id = ids[0]
        self._rebuild_blend()
        with self._lock:
            self._cache.clear()

    # ------------------------------------------------- register (đa sắc thái)
    def add_named_voice(self, name: str, path: str,
                        denoise: Optional[bool] = None,
                        use_ref_codes: Optional[bool] = None) -> bool:
        """Đăng ký một clip mẫu thành voice CÓ TÊN cho ngân hàng register.

        Dùng chung cơ chế nhân bản như set_reference nhưng KHÔNG đổi giọng đang
        dùng — chỉ thêm một voice nội bộ để RegisterBank gọi khi cần.
        """
        if not self.ready:
            raise RuntimeError(self.error or "VieNeu chua san sang")
        if not path or not os.path.exists(path):
            return False
        if denoise is None:
            denoise = os.environ.get("VIENEU_DENOISE", "1") not in ("0", "false", "False")
        if use_ref_codes is None:
            use_ref_codes = os.environ.get("VIENEU_REF_CODES", "1") not in ("0", "false", "False")
        try:
            try:
                self.tts.remove_voice(name, save=False)
            except Exception:
                pass
            self.tts.add_voice(name, path, denoise=denoise, use_ref_codes=use_ref_codes)
        except ModuleNotFoundError as e:
            raise RuntimeError(
                "Nhan ban giong can cai them torch. Chay: "
                "pip install torch torchaudio --index-url "
                "https://download.pytorch.org/whl/cpu"
            ) from e
        return True

    def synth_register(self, text: str, voice_id: Optional[str] = None,
                       temperature: Optional[float] = None) -> bytes:
        """Tổng hợp bằng MỘT voice + temperature cụ thể, qua đường 'chống rỗng'.

        RegisterBank gọi hàm này để mỗi sắc thái thừa hưởng retry + fallback về
        giọng mặc định, thay vì gọi thẳng tts.infer.
        """
        if not self.ready:
            raise RuntimeError(self.error or "VieNeu chua san sang")
        text = (text or "").strip()
        if not text:
            raise ValueError("Van ban rong")
        if _is_trivial(text):
            return _silence_wav()
        v = voice_id or self.voice_id
        kw = {}
        t = temperature if temperature is not None else self.temperature
        if t is not None:
            kw["temperature"] = t
        with self._synth_lock:
            wav = self._synth_retry(v, text, kw, tries=4)
            if len(wav) > 44:
                return wav
            default = self._default_preset()
            if default and default != v:
                wav2 = self._synth_retry(default, text, kw, tries=2)
                if len(wav2) > 44:
                    return wav2
        return _silence_wav()

    # ------------------------------------------------------------- synthesize
    def synthesize(self, text: str) -> bytes:
        if not self.ready:
            raise RuntimeError(self.error or "VieNeu chua san sang")
        key = text.strip()
        if not key:
            raise ValueError("Van ban rong")

        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return cached

        # Nối tiếp việc tạo giọng: các yêu cầu (kể cả nạp trước) xếp hàng, và
        # yêu cầu trùng câu chỉ tạo một lần (kiểm tra lại cache trong khoá).
        with self._synth_lock:
            with self._lock:
                cached = self._cache.get(key)
                if cached is not None:
                    self._cache.move_to_end(key)
                    return cached
            wav = self._infer_wav(key)
            if len(wav) <= 44:
                raise RuntimeError("VieNeu khong tao duoc audio.")
            with self._lock:
                self._cache[key] = wav
                self._cache.move_to_end(key)
                while len(self._cache) > self._cache_size:
                    self._cache.popitem(last=False)
            return wav

    def _default_preset(self) -> Optional[str]:
        return self.voices[0][1] if self.voices else None

    def _infer_wav(self, text: str) -> bytes:
        # Đoạn chỉ có số/ký hiệu -> trả khoảng lặng ngắn, khỏi làm model sinh rỗng.
        if _is_trivial(text):
            return _silence_wav()
        kw = {}
        if self.temperature is not None:
            kw["temperature"] = self.temperature
        # Bật "mượn ngữ điệu": thử 1 lần; rỗng/lỗi -> bỏ qua, dùng giọng chính.
        if self.cloned and self._blend_voice:
            try:
                wav = self._synth(self._blend_voice, text, kw)
            except Exception:
                wav = b""
            if len(wav) > 44:
                return wav
            self._blend_failed = True
        # Giọng chính (clone thuần hoặc preset): thử lại nếu model sinh rỗng.
        wav = self._synth_retry(self.voice_id, text, kw, tries=4)
        if len(wav) > 44:
            return wav
        # Cứu cánh: dùng giọng preset mặc định (Thục Đoan) để luôn có tiếng.
        default = self._default_preset()
        if default and default != self.voice_id:
            wav2 = self._synth_retry(default, text, kw, tries=2)
            if len(wav2) > 44:
                return wav2
        # Vẫn rỗng (rất hiếm) -> trả khoảng lặng để playback không đứng/văng lỗi.
        return _silence_wav()

    def _synth_retry(self, voice, text: str, kw: dict, tries: int = 4) -> bytes:
        last = b""
        for _ in range(max(1, tries)):
            try:
                wav = self._synth(voice, text, kw)
            except Exception:
                wav = b""
            if len(wav) > 44:
                return wav
            last = wav
        return last

    def _synth(self, voice, text: str, kw: dict) -> bytes:
        audio = self.tts.infer(_prep_text(text), voice=voice, **kw)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "o.wav"
            self.tts.save(audio, str(out))
            return out.read_bytes()

    # ------------------------------------------------------------- status
    def status(self) -> dict:
        cloned = self.cloned
        return {
            "ready": self.ready,
            "mode": "vieneu",
            "cloned": cloned,
            "voice": "Giọng nhân bản" if cloned else (self.voice_label or self.voice_id),
            "error": self.error,
        }
