# Hướng dẫn dùng notebook PDF → sách nói (OmniVoice trên Colab)

Notebook: `colab/PDF_to_OmniVoice_Colab.ipynb`. Mọi dữ liệu của mỗi cuốn sách nằm trên Google Drive tại `MyDrive/omnivoice_render/<tên_sách>/`, nên đóng tab, runtime bị ngắt hay mở notebook mới đều không mất gì.

---

## A. Chuẩn bị một lần

1. **Mở notebook trong Colab**, chọn một trong hai cách:
   - **Từ GitHub (khuyên dùng):** vào [colab.research.google.com](https://colab.research.google.com) → *File → Open notebook* → tab **GitHub** → dán `nguyenkha283/kindle-voice` → ở ô *Branch* chọn `claude/eloquent-noether-h8i4wo` → bấm vào `colab/PDF_to_OmniVoice_Colab.ipynb`.
   - **Từ file:** *File → Upload notebook* → chọn file `.ipynb` Claude gửi.
2. **Lưu một bản vào Drive:** *File → Save a copy in Drive*. Từ giờ luôn mở bản này: Drive → thư mục *Colab Notebooks*.
3. **Bật GPU:** *Runtime → Change runtime type* → chọn **T4 GPU** → *Save*.
4. **Chuẩn bị clip giọng mẫu:** một người đọc, 6–10 giây, phòng yên tĩnh. Ghi lại đúng lời đọc trong clip để điền vào `REF_TEXT` ở mục 5. Cách thu: xem `huong-dan-thu-clip-mau.md` ở thư mục gốc của repo.
5. *(Tùy chọn)* **Clip sắc thái:** cùng người đọc, cùng mic, mỗi file đọc đúng một sắc thái và đặt tên đúng tên sắc thái: `doi_thoai.wav`, `tinh_cam.wav`, `kich_tinh.wav`, `vui_tuoi.wav`, `goi_cam.wav`. Không có cũng được: khi đó chỉ tốc độ và khoảng nghỉ thay đổi theo sắc thái.
6. *(Chỉ khi muốn dùng Claude để gán sắc thái)* Bấm biểu tượng 🔑 ở thanh bên trái → *Add new secret* → tên `ANTHROPIC_API_KEY`, dán key → bật *Notebook access*.

---

## B. Làm một cuốn sách mới

Chạy từng ô từ trên xuống (bấm ▶ bên trái ô, hoặc Shift+Enter). Bảng dưới chỉ ghi những gì cần **sửa hoặc để ý**; ô nào không nhắc thì cứ chạy.

| Mục | Làm gì | Để ý |
|---|---|---|
| **0** GPU | Chạy | Phải thấy `Tesla T4`. Không thấy thì làm lại bước A.3 |
| **1** Cài đặt | Chạy | Mất 1–2 phút |
| **2a** PDF | Để `BOOK = ''`, chạy, bấm *Choose files*, chọn PDF | Colab xin quyền truy cập Drive: đồng ý. **Ghi lại tên thư mục** in ra, vd `that_lac_coi_nguoi`; lần sau cần đến |
| **2b** Giọng mẫu | Chạy, chọn clip giọng | |
| **3** Code | Chạy | In ra `Code: <mã> <ngày> ...` là bản code đang dùng |
| **4** Tách câu | Chạy, **đọc kỹ** câu đầu, câu giữa và các câu được chuẩn hoá | Thấy số trang, chú thích hay tiêu đề lặp lẫn vào câu thì báo Claude trước khi render. PDF là bản scan thì đặt `OCR = True` (xem ô ngay dưới) |
| **4b** ô 1 | Có clip sắc thái thì đặt `UPLOAD_REGISTERS = True`, chạy, chọn các clip | Bảng in ra: `↩` = chưa có clip riêng, đang dùng clip dự phòng |
| **4b** ô 2 | Chạy với `TAGGER = 'local'` | Lần đầu tải model khoảng 8 GB (vài phút). Xem mục C bên dưới để chỉnh `NGUONG` |
| **5** Cấu hình | Điền `REF_TEXT` = **đúng lời** trong clip giọng mẫu; có clip sắc thái thì điền `REG_TEXTS` | Để trống thì Whisper tự chép lời; chép sai một chữ là clone kém đi |
| **6** Nạp model | Chạy | In `Đã có giọng clone: ...` |
| **7** Render | **Lần đầu để `LIMIT = 30`**, chạy, nghe thử (mục D). Ổn thì đặt `LIMIT = None`, chạy lại | Dòng `⏱ Benchmark` cho biết cả cuốn mất bao nhiêu giờ GPU. Có thể bấm ⏹ bất cứ lúc nào, phần đã render vẫn được lưu |
| **8** Báo cáo | Chạy | Chương ✅ là đã render đủ |
| **9** Ghép mp3 | Chạy | `MODE = 'chapter'`: mỗi chương 1 file; `'book'`: cả cuốn 1 file |
| **10** Tải về | Mở drive.google.com → `omnivoice_render/<tên_sách>/mp3/` → chuột phải → *Download* | |

---

## C. Chỉnh sắc thái (mục 4b ô 2)

Ô in một bảng, ví dụ:

```
Ngưỡng → số câu đọc bằng giọng cảm xúc:
  NGUONG = 0.5:    42 câu (15.2%)
  NGUONG = 0.6:    25 câu ( 9.0%)   ← đang dùng
  NGUONG = 0.7:    11 câu ( 4.0%)
```

và 3 câu mẫu cho mỗi sắc thái.

- **Quá nhiều câu cảm xúc**, hoặc các câu mẫu không hợp lý: tăng `NGUONG` (0.7, 0.8). **Quá ít:** giảm `NGUONG`. Sách kể chuyện thường hợp với khoảng 5–15%.
- Sửa `NGUONG` rồi **chỉ chạy lại ô này**: chỉ mất vài giây, không chạy lại model.
- Một vài câu sai thì sửa tay: `OVERRIDES = {61: 'trung_tinh', 120: 'tinh_cam'}`. Số thứ tự câu là số trong ngoặc vuông `[61 | tr.4]`.
- Ở mọi ngưỡng vẫn sai nhiều: thử model lớn hơn bằng `LOCAL_MODEL = 'Qwen/Qwen3-8B'`, `LOCAL_4BIT = True`, `RESCORE = True`. Chạy lại ô, rồi đặt `RESCORE = False`.
- Đổi tốc độ hay khoảng nghỉ của một sắc thái: thêm một ô **ngay sau mục 3**, ví dụ:
  ```python
  sac_thai.REGISTERS['tinh_cam']['speed'] = 0.95   # 1.0 = bình thường, nhỏ hơn = chậm hơn
  sac_thai.REGISTERS['tinh_cam']['pause'] = 1.4    # nhân khoảng nghỉ sau câu
  ```
- Sau khi đổi sắc thái, chạy lại **mục 7**: chỉ những câu đổi sắc thái phải render lại.

---

## D. Nghe thử trước khi render cả cuốn

Sau khi mục 7 chạy với `LIMIT = 30`, thêm một ô mới (*+ Code*) rồi dán:

```python
from IPython.display import Audio, display
shown = 0
for u in units:
    f = OUT/f"{u['key']}.wav"
    if f.exists():
        print(f"[{u['i']}] {u['reg']}: {u['text'][:100]}")
        display(Audio(str(f)))
        shown += 1
    if shown >= 10:
        break
```

Muốn nghe riêng các câu có sắc thái, đổi `if f.exists():` thành `if f.exists() and u['reg'] != 'trung_tinh':`. Câu có sắc thái thường nằm sau 30 câu đầu, nên phải render thêm (tăng `LIMIT`) mới nghe được.

Nghe được khoảng 30 câu rồi mới quyết định. Nếu cần:
- `NUM_STEP = 16`: nhanh gấp khoảng 2 lần, kém nét hơn một chút.
- Đổi clip giọng mẫu (nhớ đổi cả `VOICE_ID`).

---

## E. Runtime bị ngắt, hoặc hôm sau làm tiếp

1. Mở lại notebook (bản đã lưu trong Drive).
2. Ở mục 2a đặt `BOOK = 'tên_thư_mục'`, đúng tên đã ghi ở bước B.
3. Chạy lần lượt mục **0 → 7**, hoặc *Runtime → Run before* ở ô mục 7. Chạy hết mục 7 thì nó tự khôi phục các câu đã render từ Drive và chỉ render tiếp phần còn thiếu. Ô 2b tự dùng giọng mẫu đã lưu. Ô 4b không chạy lại model nếu điểm sắc thái đã có.

---

## F. Khi Claude báo đã có bản sửa code

**Không cần mở notebook mới.** Trong notebook đang mở:

1. Chạy lại **mục 3**. Dòng `Code: ...` phải hiện mã mới, đúng mã Claude báo.
2. Chạy lại các mục Claude dặn, thường là **4 → 4b**, rồi **7** nếu có câu cần render lại.

Runtime đã bị ngắt từ trước thì làm như mục E: chạy 0 → 7 là tự có code mới.

Chỉ phải mở notebook mới khi Claude báo đã sửa **chính file notebook** (các ô render ở mục 7, ghép mp3 ở mục 9). Khi đó mở bản mới theo bước A.1 rồi làm như mục E. Dữ liệu trên Drive vẫn còn nguyên.

---

## G. Lỗi thường gặp

| Thấy gì | Làm gì |
|---|---|
| `CUDA out of memory` ở mục 4b | Giảm `LOCAL_BATCH` (4, 2). Vẫn lỗi: *Runtime → Restart session*, chạy lại 0 → 4b |
| `CUDA out of memory` ở mục 6 hoặc 7 | *Runtime → Restart session*, chạy lại 0 → 7. Mục 4b sẽ không nạp lại model vì điểm đã lưu |
| `Hãy chạy ô 2a (upload PDF) trước` / `NameError` | Bỏ sót một ô phía trên. Chạy lại từ mục 2a |
| `Không thấy '<tên>' trên Drive → coi như sách mới` | Gõ sai `BOOK`. Xem tên đúng trong Drive → `omnivoice_render/` |
| Mục 3 báo lỗi `git` | Kiểm tra mạng, chạy lại ô. Vẫn lỗi thì gửi Claude dòng lỗi |
| Câu bị loại (`loại=` > 0) ở mục 7 | Xem `failed.jsonl` trong thư mục sách. Muốn render bù: `RETRY_FAILED = True` rồi chạy lại mục 7 |
| Colab tự ngắt sau vài giờ | Bình thường với Colab miễn phí. Làm theo mục E |

Gặp lỗi khác: chụp màn hình hoặc copy vài dòng cuối của ô bị lỗi gửi Claude.
