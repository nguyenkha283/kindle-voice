"""Máy chủ cục bộ cho trình đọc sách + đọc voice offline.

Chạy hoàn toàn trên máy bạn: phục vụ giao diện web và tổng hợp giọng nói bằng
Piper. Không gửi dữ liệu ra ngoài.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from epub_parser import parse_epub, get_cover_bytes, book_id_for, Book
from pdf_parser import parse_pdf
from tts_engine import TTSEngine

ROOT = Path(__file__).resolve().parent.parent
BOOKS_DIR = Path(os.environ.get("BOOKS_DIR", ROOT / "books"))
VOICES_DIR = Path(os.environ.get("VOICES_DIR", ROOT / "voices"))
REFERENCE_DIR = Path(os.environ.get("REFERENCE_DIR", ROOT / "reference"))
FRONTEND_DIR = ROOT / "frontend"
BOOKS_DIR.mkdir(parents=True, exist_ok=True)
VOICES_DIR.mkdir(parents=True, exist_ok=True)
REFERENCE_DIR.mkdir(parents=True, exist_ok=True)


def _pick_voice_model() -> Path | None:
    env = os.environ.get("VOICE_MODEL")
    if env and Path(env).exists():
        return Path(env)
    models = sorted(VOICES_DIR.glob("*.onnx"))
    return models[0] if models else None


app = FastAPI(title="Kindle Voice (offline)")

_PROVIDER = os.environ.get("TTS_PROVIDER", "piper").lower()

# ==== Cờ GIỌNG RIÊNG (register đa sắc thái + nhân bản giọng) ====
# "0" = TẮT giọng riêng -> đọc bằng giọng mặc định VieNeu (Thục Đoan).
#       (File trung_tinh.wav... vẫn giữ nguyên, chỉ không dùng tới.)
# Bật lại: đổi "0" thành "1" ở dòng dưới rồi push (hoặc đặt env USE_CUSTOM_VOICE=1).
USE_CUSTOM_VOICE = os.environ.get("USE_CUSTOM_VOICE", "0") in ("1", "true", "True", "yes")

if _PROVIDER == "vieneu":
    from vieneu_engine import VieNeuEngine
    tts = VieNeuEngine()
    # Nạp lại giọng mẫu đã tải trước đó (nếu có) hoặc từ VIENEU_REF_AUDIO.
    _ref = os.environ.get("VIENEU_REF_AUDIO")
    if not _ref:
        _clips = sorted(REFERENCE_DIR.glob("clip.*"))
        _ref = str(_clips[0]) if _clips else None
    if USE_CUSTOM_VOICE and _ref and hasattr(tts, "set_reference"):
        try:
            tts.set_reference(_ref)
        except Exception:
            pass  # thiếu torch hoặc mẫu lỗi -> bỏ qua, dùng giọng preset
else:
    tts = TTSEngine(_pick_voice_model())

# ---------------------------------- Ngân hàng register (sắc thái giọng, VieNeu)
# Chỉ bật ở chế độ VieNeu. Chưa có clip trong references/registers/ thì _bank rỗng
# và app đọc bằng giọng mặc định như cũ. Thả đủ clip vào là tự bật.
_bank = None
_tagger = None
if _PROVIDER == "vieneu" and USE_CUSTOM_VOICE:
    try:
        from registers import RegisterBank
        from tagging import Tagger
        _bank = RegisterBank(tts)
        _bank.load()
        _tagger = Tagger(use_llm=bool(os.environ.get("ANTHROPIC_API_KEY")))
    except Exception as e:  # noqa: BLE001
        print(f"[app] Register bank tat: {e}")
        _bank = None
        _tagger = None


def _synth_text(text: str) -> bytes:
    """Chọn đường tổng hợp: có register (đa sắc thái) thì dùng, không thì engine gốc."""
    if _bank is not None and _bank.available():
        reg = _tagger.tag(text) if _tagger else None
        return _bank.synthesize(text, register=reg)
    return tts.synthesize(text)


# Cache sách đã parse: id -> (mtime, Book)
_book_cache: dict[str, tuple[float, Book]] = {}


SUPPORTED_EXT = (".epub", ".pdf")


def _iter_books() -> list[Path]:
    files = [p for p in BOOKS_DIR.iterdir()
             if p.is_file() and p.suffix.lower() in SUPPORTED_EXT]
    return sorted(files)


def _path_for_id(book_id: str) -> Path | None:
    for p in _iter_books():
        if book_id_for(p) == book_id:
            return p
    return None


def _parse_any(path: Path) -> Book:
    if path.suffix.lower() == ".pdf":
        return parse_pdf(path)
    return parse_epub(path)


def _load_book(path: Path) -> Book:
    mtime = path.stat().st_mtime
    cached = _book_cache.get(book_id_for(path))
    if cached and cached[0] == mtime:
        return cached[1]
    book = _parse_any(path)
    _book_cache[book.id] = (mtime, book)
    return book


# --------------------------------------------------------------------- API
@app.get("/api/status")
def status():
    return {"tts": tts.status(), "provider": _PROVIDER, "book_count": len(_iter_books())}


@app.get("/api/voices")
def list_voices():
    return {
        "provider": _PROVIDER,
        "current": getattr(tts, "voice_id", None),
        "blend": getattr(tts, "blend_from", None),
        "voices": tts.list_voices(),
        "custom_voice": USE_CUSTOM_VOICE,
    }


class VoiceReq(BaseModel):
    voice_id: str


@app.post("/api/voice")
def set_voice(req: VoiceReq):
    if tts.set_voice(req.voice_id):
        return {"ok": True, "voice": tts.status().get("voice")}
    raise HTTPException(400, "Giọng không hợp lệ hoặc engine không hỗ trợ đổi giọng")


class BlendReq(BaseModel):
    voice_id: Optional[str] = None


@app.post("/api/voice/blend")
def set_blend(req: BlendReq):
    if not USE_CUSTOM_VOICE:
        raise HTTPException(403, "Tính năng giọng riêng đang tắt.")
    if not hasattr(tts, "set_blend"):
        raise HTTPException(400, "Engine không hỗ trợ mượn ngữ điệu.")
    if tts.set_blend(req.voice_id or None):
        return {"ok": True, "blend": getattr(tts, "blend_from", None)}
    raise HTTPException(400, "Preset không hợp lệ.")


@app.post("/api/voice/clone")
async def clone_voice(file: UploadFile = File(...), denoise: str = Form("0")):
    if not USE_CUSTOM_VOICE:
        raise HTTPException(403, "Tính năng giọng riêng đang tắt.")
    if not hasattr(tts, "set_reference"):
        raise HTTPException(400, "Engine hiện tại không hỗ trợ nhân bản giọng (chỉ VieNeu).")
    name = os.path.basename(file.filename or "")
    ext = os.path.splitext(name)[1].lower() or ".wav"
    if ext not in (".wav", ".mp3", ".m4a", ".flac", ".ogg"):
        raise HTTPException(400, "Định dạng âm thanh không hỗ trợ (dùng .wav là tốt nhất).")
    for old in REFERENCE_DIR.glob("clip.*"):
        try: old.unlink()
        except Exception: pass
    dest = REFERENCE_DIR / f"clip{ext}"
    dest.write_bytes(await file.read())
    dn = denoise not in ("0", "false", "False", "")
    try:
        ok = tts.set_reference(str(dest), denoise=dn)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    if ok:
        return {"ok": True, "voice": "Giọng nhân bản", "denoise": dn}
    raise HTTPException(500, "Không dùng được file mẫu.")


@app.get("/api/books")
def list_books():
    out = []
    for p in _iter_books():
        try:
            out.append(_load_book(p).meta_dict())
        except Exception as e:  # noqa: BLE001
            out.append({
                "id": book_id_for(p), "title": p.name, "author": "",
                "has_cover": False, "chapter_count": 0, "error": str(e),
            })
    return out


@app.get("/api/books/{book_id}")
def get_book(book_id: str):
    path = _path_for_id(book_id)
    if not path:
        raise HTTPException(404, "Không tìm thấy sách")
    try:
        return _load_book(path).full_dict()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"Lỗi đọc EPUB: {e}")


@app.get("/api/books/{book_id}/cover")
def get_cover(book_id: str):
    path = _path_for_id(book_id)
    if not path:
        raise HTTPException(404, "Không tìm thấy sách")
    if path.suffix.lower() != ".epub":       # PDF chưa hỗ trợ ảnh bìa -> dùng bìa tự sinh
        raise HTTPException(404, "Sách không có ảnh bìa")
    data = get_cover_bytes(path)
    if not data:
        raise HTTPException(404, "Sách không có ảnh bìa")
    return Response(content=data, media_type="image/jpeg")


@app.delete("/api/books/{book_id}")
def delete_book(book_id: str):
    path = _path_for_id(book_id)
    if not path:
        raise HTTPException(404, "Không tìm thấy sách")
    try:
        path.unlink()
    except OSError as e:
        raise HTTPException(500, f"Không xóa được: {e}")
    _book_cache.pop(book_id, None)
    return {"ok": True, "deleted": book_id}


MUSIC_DIR = Path(os.environ.get("MUSIC_DIR", ROOT / "frontend" / "music"))


@app.get("/api/music")
def list_music():
    """Liệt kê nhạc nền trong frontend/music/ thành thư viện cho app."""
    if not MUSIC_DIR.exists():
        return []
    exts = (".mp3", ".ogg", ".m4a", ".wav")
    out = []
    for p in sorted(MUSIC_DIR.iterdir()):
        if p.suffix.lower() in exts:
            nice = p.stem.replace("_", " ").replace("-", " ").strip()
            out.append({"name": nice.title() or p.name, "src": f"/music/{p.name}"})
    return out


@app.post("/api/upload")
async def upload_book(file: UploadFile = File(...)):
    name = os.path.basename(file.filename or "")
    if not name.lower().endswith(SUPPORTED_EXT):
        raise HTTPException(400, "Chỉ nhận file .epub hoặc .pdf")
    dest = BOOKS_DIR / name
    dest.write_bytes(await file.read())
    try:
        book = _load_book(dest)
        return book.meta_dict()
    except Exception as e:  # noqa: BLE001
        try:
            dest.unlink()                       # bỏ file hỏng để khỏi kẹt thư viện
        except OSError:
            pass
        raise HTTPException(400, f"Không đọc được sách: {e}")


class TTSRequest(BaseModel):
    text: str


@app.post("/api/tts")
def synth(req: TTSRequest):
    if not tts.ready:
        return JSONResponse(
            status_code=503,
            content={"error": tts.error, "hint": "Xem README để tải mô hình giọng."},
        )
    try:
        wav = _synth_text(req.text)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"Lỗi tổng hợp giọng: {e}")
    return Response(content=wav, media_type="audio/wav")


# --------------------------------------------------- register (đa sắc thái)
@app.get("/api/registers")
def registers_status():
    """Trạng thái ngân hàng sắc thái: đã nạp clip nào, có bật phân loại LLM không."""
    if _bank is None:
        return {"enabled": False, "available": [],
                "note": "Chỉ có ở chế độ VieNeu (TTS_PROVIDER=vieneu)."}
    return {
        "enabled": True,
        "available": _bank.available(),
        "dir": str(_bank.dir),
        "llm_tagging": bool(_tagger and _tagger.llm and _tagger.llm.enabled),
    }


class PrerenderReq(BaseModel):
    texts: list[str]


@app.post("/api/prerender")
def prerender(req: PrerenderReq):
    """Nạp trước (nền) audio cho một loạt đơn vị -> playback sau này tức thì.

    Tùy chọn: frontend có thể gọi khi mở chương, truyền danh sách câu sắp đọc.
    Không gọi cũng không sao — cache vẫn được hâm nóng bởi prefetch sẵn có.
    """
    if _bank is None or not _bank.available():
        return {"ok": False, "reason": "register chưa bật (chưa có clip mẫu)."}
    import threading

    def _warm(texts: list[str]) -> None:
        for t in texts:
            try:
                reg = _tagger.tag(t) if _tagger else None
                _bank.synthesize(t, register=reg)   # ghi vào cache đĩa
            except Exception:
                pass

    threading.Thread(target=_warm, args=(list(req.texts),), daemon=True).start()
    return {"ok": True, "queued": len(req.texts)}


# ----------------------------------------------------------------- frontend
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
