# PROJECT — Đọc & Nghe (kindle-voice)

> Tài liệu theo dõi dự án dành cho lập trình viên. Mục tiêu: giúp người mới nắm
> nhanh **dự án làm gì**, **code nằm ở đâu**, **đã làm được đến đâu** và **còn gì
> phải làm**. README.md là hướng dẫn cho người dùng cuối; file này là hướng dẫn
> cho người phát triển.

Cập nhật lần cuối: 2026-09-16

---

## 1. Dự án là gì

Web app **chạy cục bộ trên máy người dùng**: đọc sách EPUB/PDF và **nghe giọng
đọc tiếng Việt hoàn toàn offline** (không gửi dữ liệu ra ngoài). Backend FastAPI
phục vụ luôn giao diện web; giọng nói tổng hợp tại chỗ bằng **Piper** hoặc
**VieNeu-TTS**. Trình đọc highlight từng câu theo lời đọc ("đèn đọc" trượt theo).

- **Ngôn ngữ:** Python (backend) + HTML/CSS/JS thuần (frontend, không cần build).
- **Chạy:** `run.sh` / `run.bat` (Piper) hoặc `run_vieneu.sh` / `.bat` (VieNeu).
- **Truy cập:** http://127.0.0.1:8000

---

## 2. Kiến trúc & cấu trúc thư mục

```
kindle-voice/
├─ backend/
│  ├─ app.py            # Máy chủ FastAPI + phục vụ frontend + định tuyến API
│  ├─ epub_parser.py    # EPUB -> chương / đoạn / câu (lọc chú thích, tách câu)
│  ├─ pdf_parser.py     # PDF  -> cùng cấu trúc Book (chia chương theo outline)
│  ├─ tts_engine.py     # Engine Piper (python hoặc binary) + cache + ngắt nghỉ
│  ├─ vieneu_engine.py  # Engine VieNeu-TTS (preset / nhân bản giọng / blend)
│  ├─ text_norm.py      # Chuẩn hoá văn bản trước TTS (số La Mã, lọc ký tự lạ)
│  ├─ registers.py      # Ngân hàng "sắc thái giọng" (chỉ VieNeu + custom voice)
│  ├─ tagging.py        # Gán sắc thái cho đoạn (heuristic / LLM tùy chọn)
│  └─ prerender.py      # Pre-render audio cả chương ra đĩa (luồng nền)
├─ frontend/            # app.js / index.html / style.css + music/
├─ books/               # Sách .epub / .pdf của người dùng
├─ voices/              # Mô hình giọng Piper (.onnx + .onnx.json)
├─ references/          # Clip mẫu nhân bản giọng & registers/
├─ cache/               # Cache audio & nhãn (tự sinh, không commit)
└─ .github/workflows/   # deploy.yml (CI/CD triển khai lên máy chủ Oracle)
```

**Luồng dữ liệu:** file sách → parser → `Book(chapters→blocks→sentences)` →
frontend dựng "đơn vị đọc" (units) → mỗi unit gọi `POST /api/tts` →
`text_norm` chuẩn hoá → engine tổng hợp WAV → phát + highlight.

---

## 3. Trạng thái tính năng

| Tính năng | Trạng thái | Ghi chú |
|---|---|---|
| Thư viện sách (thêm/xóa/kéo-thả) | ✅ Xong | `app.py`, `frontend/app.js` |
| Đọc EPUB (chương/câu, nhớ vị trí) | ✅ Xong | `epub_parser.py` |
| Đọc PDF (chữ) | ✅ Xong | `pdf_parser.py`; PDF scan ảnh chưa hỗ trợ |
| Giọng Piper offline | ✅ Xong | `tts_engine.py` |
| Giọng VieNeu-TTS offline | ✅ Xong | `vieneu_engine.py` (khuyến nghị) |
| Highlight từng câu + tự cuộn | ✅ Xong | `frontend/app.js` |
| Điều khiển tốc độ, cỡ chữ, nền, phím tắt | ✅ Xong | ghi nhớ qua localStorage |
| Nhạc nền | ✅ Xong | `GET /api/music` |
| Nhân bản giọng / mượn ngữ điệu (blend) | ✅ Xong* | *cần bật `USE_CUSTOM_VOICE=1` |
| Ngân hàng sắc thái (register) + tagging LLM | ✅ Xong* | *chỉ VieNeu + custom voice + có clip |
| Chuẩn hoá văn bản trước TTS | ✅ Xong | `text_norm.py` (PR #1) |
| Cache OmniVoice render sẵn | ✅ Xong | tra trước ở `POST /api/tts` |
| Highlight theo **từng từ** (word timestamps) | ⬜ Dự kiến | cần model xuất mốc thời gian |
| Cài như app (PWA / service worker) | ⬜ Dự kiến | chạy offline như app native |
| Hỗ trợ PDF scan (OCR) | ⬜ Dự kiến | |

---

## 4. API backend (tham chiếu nhanh)

| Method & path | Chức năng |
|---|---|
| `GET /api/status` | Trạng thái engine + số sách |
| `GET /api/voices` · `POST /api/voice` | Liệt kê / đổi giọng |
| `POST /api/voice/blend` · `POST /api/voice/clone` | Mượn ngữ điệu / nhân bản giọng |
| `GET /api/books` · `GET /api/books/{id}` | Danh sách / nội dung sách |
| `GET /api/books/{id}/cover` · `DELETE /api/books/{id}` | Ảnh bìa / xóa sách |
| `POST /api/upload` | Tải sách .epub/.pdf lên |
| `POST /api/tts` | Tổng hợp một câu -> WAV |
| `GET /api/music` | Danh sách nhạc nền |
| `GET /api/registers` · `POST /api/prerender` | Sắc thái giọng / nạp trước audio |

---

## 5. Roadmap / việc đang mở

- [ ] Highlight theo từng từ (đồng bộ mịn hơn).
- [ ] PWA + service worker để cài như app.
- [ ] OCR cho PDF scan ảnh.
- [ ] Bổ sung test tự động cho parser & `text_norm`.
- [ ] Cải thiện tách câu tiếng Việt cho trường hợp viết tắt ("TP.", "GS.").

> Việc đang làm và thảo luận: xem tab **Issues** và **Pull Requests** trên GitHub.

---

## 6. Quy ước phát triển

- **Nhánh:** làm trên nhánh riêng (vd `feature/...`), mở PR vào `main`.
- **Commit:** tiếng Việt, mô tả rõ ý; một commit làm một việc.
- **Chạy thử:** `./run_vieneu.sh` (hoặc `run.sh`) rồi mở http://127.0.0.1:8000.
- **Không commit:** thư mục `cache/`, `voices/`, `books/`, clip trong `references/`.
- **Triển khai:** push vào `main` -> GitHub Actions tự deploy qua SSH (xem mục CI).

---

## 7. Nhật ký thay đổi gần đây

| Ngày | Thay đổi | PR |
|---|---|---|
| 2026-09-16 | Chuẩn hoá văn bản trước TTS: đọc đúng đầu mục số La Mã (I, II → một, hai) & chặn "babble" đoạn không có trong sách | [#1](https://github.com/nguyenkha283/kindle-voice/pull/1) |
