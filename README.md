# Đọc & Nghe — trình đọc sách EPUB có giọng đọc offline

Một web app chạy **ngay trên máy bạn**: đọc sách EPUB và **nghe giọng đọc tiếng Việt hoàn toàn offline** (không gửi dữ liệu ra ngoài, không cần mạng khi đọc). Giao diện mở bằng trình duyệt, phần giọng nói do một máy chủ nhỏ trên máy bạn tổng hợp bằng **Piper**.

Đây là bản **MVP**: thư viện sách, đọc EPUB (chia chương, nhớ vị trí đọc), và trình đọc voice có highlight từng câu theo giọng nói ("đèn đọc" màu hổ phách trượt theo lời đọc).

---

## 1. Yêu cầu
- **Python 3.9+**
- Kết nối mạng **một lần** để cài thư viện và tải mô hình giọng (sau đó chạy offline).

## 2. Chạy nhanh (3 bước)

**macOS / Linux**
```bash
./run.sh            # tạo .venv, cài thư viện, chạy server
```

**Windows**
```bat
run.bat
```

Rồi mở trình duyệt: **http://127.0.0.1:8000**

> Lần đầu chạy, giọng đọc chưa có nên nút Phát sẽ báo cần cài giọng. Làm bước 3.

## 3. Tải giọng tiếng Việt (một lần)

Giọng mặc định: **vi_VN-vais1000-medium** (Piper, ~63MB).

**macOS / Linux**
```bash
./download_voice.sh
```
**Windows**
```bat
download_voice.bat
```

Tải xong, **khởi động lại server** (tắt rồi chạy lại `run.sh` / `run.bat`). Trên thư viện, huy hiệu góc phải sẽ chuyển thành *"Giọng: vi_VN-vais1000-medium.onnx"*.

> Muốn dùng giọng khác: tải cặp file `.onnx` + `.onnx.json` bất kỳ của Piper vào thư mục `voices/`. App tự nhận file `.onnx` đầu tiên. Có thể chỉ định rõ bằng biến môi trường `VOICE_MODEL=/đường/dẫn.onnx`.

---

## Nếu cài `piper-tts` bị lỗi (Cách 2: dùng binary)

Trên vài máy (thường macOS Apple Silicon), `pip install piper-tts` có thể lỗi phần phụ thuộc. App vẫn chạy được — chỉ cần dùng **binary piper**:

1. Tải bản binary phù hợp hệ điều hành ở trang phát hành Piper (`github.com/rhasspy/piper` hoặc `github.com/OHF-Voice/piper1-gpl`).
2. Đặt file chạy tên `piper` (hoặc `piper.exe`) vào **PATH**, hoặc ngay trong thư mục `voices/`, hoặc trỏ bằng biến môi trường `PIPER_BIN=/đường/dẫn/piper`.
3. Vẫn cần cặp file mô hình `.onnx` + `.onnx.json` trong `voices/` (bước 3 ở trên).

Server sẽ tự ưu tiên gói Python, nếu không có thì tự chuyển sang binary.

---

## Giọng VieNeu-TTS — tự nhiên hơn, vẫn offline (khuyến nghị)

Piper đọc đôi khi sai âm. Muốn giọng tiếng Việt tự nhiên/chuẩn hơn mà **vẫn offline, không cần GPU**, dùng **VieNeu-TTS v3 Turbo** (chạy trên CPU qua ONNX).

Thay vì `run.bat`, chạy:

**Windows**
```bat
run_vieneu.bat
```
**macOS / Linux**
```bash
./run_vieneu.sh
```

Script sẽ tự `pip install vieneu`, bật chế độ VieNeu và khởi động. **Lần đầu sẽ tải model (~vài trăm MB) — cần mạng một lần**, sau đó chạy offline. Mở `http://127.0.0.1:8000` như thường; huy hiệu sẽ hiện tên giọng VieNeu.

Ghi chú:
- Không cần tải giọng Piper (bước 3) nếu bạn chỉ dùng VieNeu.
- Đổi giọng: mở `run_vieneu.bat`/`.sh`, bỏ dấu chú thích ở dòng `VIENEU_VOICE` và điền tên giọng preset; hoặc đặt biến môi trường `VIENEU_VOICE`. Danh sách giọng có sẵn được nạp tự động khi chạy.
- Nét hơn (chậm hơn): đặt `VIENEU_PRECISION=fp32` (mặc định `int8` nhẹ & nhanh).
- VieNeu tự lo ngắt nghỉ & phát âm nên phần chèn khoảng lặng thủ công của Piper được tự động bỏ qua ở chế độ này.
- Muốn quay lại Piper: chạy `run.bat`/`run.sh` như cũ.

### Nhân bản giọng (đọc bằng giọng bạn chọn)

Nếu không giọng preset nào hợp, dùng **nhân bản giọng**: trong trình đọc bấm **"Nhân bản giọng"**, chọn một file âm thanh mẫu — app sẽ đọc sách bằng chính giọng trong mẫu đó, vẫn offline.
- Mẫu tốt: **~10–15 giây** giọng nói **sạch, rõ, không nhạc nền**, định dạng **.wav** là tốt nhất.
- Chỉ nhân bản giọng bạn có quyền dùng (giọng của chính bạn là hợp lý nhất).
- Đổi lại giọng preset bất cứ lúc nào bằng ô chọn giọng. Mẫu được lưu ở thư mục `reference/` và tự dùng lại cho lần chạy sau.
- Nhân bản giọng cần thêm `torch` (bản CPU) — `run_vieneu` đã tự cài. Nếu cài tay: `pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu`.
- App mặc định chỉ dùng **một giọng: Thục Đoan** (nữ · Nam · kể chuyện); các giọng preset khác được ẩn cho gọn. Muốn đổi giọng mặc định khác, đặt biến môi trường `VIENEU_ONLY=<Tên giọng>` (hoặc để trống `VIENEU_ONLY=` để hiện lại tất cả).

## Cách dùng
- **Thêm sách:** bấm *Thêm sách* hoặc kéo–thả file `.epub` vào cửa sổ.
- **Đọc:** bấm vào bìa để mở. Đổi chương bằng ô chọn ở trên; đổi cỡ chữ (A− / A+) và nền đọc (sáng / ngà / tối).
- **Nghe:** bấm ▶ để nghe từ đầu, hoặc **bấm vào một câu bất kỳ** để đọc từ đó. Câu đang đọc sẽ sáng lên và tự cuộn theo.
- **Điều khiển:** ⏮ / ⏭ chuyển câu, thanh **Tốc độ** 0.75×–1.75×. Hết chương tự sang chương sau.
- **Phím tắt:** `Space` phát/dừng, `←` `→` chuyển câu.
- Vị trí đọc, cỡ chữ, nền và tốc độ được **nhớ lại** cho lần sau.

## Cấu trúc thư mục
```
kindle-voice/
├─ run.sh / run.bat              # chạy app
├─ download_voice.sh / .bat      # tải giọng tiếng Việt
├─ requirements.txt
├─ backend/
│  ├─ app.py                     # máy chủ FastAPI + phục vụ giao diện
│  ├─ epub_parser.py             # đọc EPUB -> chương / đoạn / câu
│  └─ tts_engine.py              # Piper (python hoặc binary) + cache
├─ frontend/                     # giao diện (HTML/CSS/JS, không cần build)
├─ books/                        # sách .epub của bạn
└─ voices/                       # mô hình giọng .onnx
```

---

## Giới hạn của bản MVP & hướng nâng cấp
- **Giọng:** hiện dùng Piper (medium) — rõ, dễ nghe nhưng chưa thật tự nhiên. Hướng nâng cấp: gắn mô hình tiếng Việt chất lượng cao hơn (ví dụ VieNeu-TTS) qua cùng lớp `tts_engine.py`; đổi lại nặng hơn và mỗi câu tạo chậm hơn.
- **Định dạng:** mới hỗ trợ **EPUB**. PDF (loại có chữ) sẽ thêm sau bằng `pdf.js`/trích text ở backend.
- **Offline "cài lên máy" (PWA):** chưa bật; có thể bổ sung service worker để cài như app và chạy khi mất mạng.
- **Đồng bộ giọng:** hiện highlight theo **từng câu**. Muốn highlight theo **từng từ** cần mô hình xuất mốc thời gian (word timestamps).

> Khi làm phần giọng tự nhiên hơn (mô hình nặng), nên chạy ở mức model/effort cao hơn để chắc tay.
