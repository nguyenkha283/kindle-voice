# Hướng dẫn thu bộ clip mẫu (reference bank) cho giọng đọc

Mục tiêu: thu **một giọng của bạn ở nhiều sắc thái** để app đổi ngữ điệu theo ngữ cảnh
(kể chuyện phẳng, đối thoại, tình cảm, gợi cảm) mà **danh tính giọng vẫn là một người**.

Nguyên tắc vàng: model cloning bắt chước **cả chất giọng lẫn cách đọc** của clip mẫu.
Vì vậy nội dung đọc và cách đọc trong mỗi clip phải *đúng sắc thái* bạn muốn nhận lại.

---

## 0. Chuẩn bị nhanh (checklist trước khi thu)

- [ ] Phòng yên tĩnh, ít vang (nhiều đồ mềm: rèm, chăn, tủ quần áo mở). Tránh phòng trống tường cứng.
- [ ] Tắt quạt, máy lạnh ồn, điện thoại để im lặng, đóng cửa sổ.
- [ ] Mic cố định một loại cho **cả buổi** (mic USB rẻ tốt hơn mic điện thoại, nhưng *nhất quán* quan trọng hơn *đắt tiền*).
- [ ] Khoảng cách miệng–mic ~15–20 cm, hơi chếch để tránh bật hơi (âm "p", "b", "t").
- [ ] Uống nước, hắng giọng, đọc thử vài câu cho ấm giọng trước khi thu thật.

## 1. Thông số kỹ thuật

- Định dạng: **WAV, mono**, tần số ≥ 24 kHz (khớp VieNeu).
- Mức âm lượng: nói đều, **không để đỉnh chạm mức tối đa** (tránh méo/clipping). Để dư "trần" một chút.
- Độ dài mỗi clip: nhắm **6–8 giây** đọc liền mạch, tự nhiên, không vấp.
  (VieNeu tự cắt còn ≤ 8 giây và tự khử nhiễu, nên bạn thu hơi dư rồi để nó xử lý.)
- Mỗi register thu **3–5 lần**, sau đó chọn bản sạch và đúng sắc thái nhất.

## 2. Các register cần thu

Thu lần lượt 4 register lõi. Với mỗi cái: đọc **kịch bản mẫu** bên dưới đúng "cách đọc" mô tả.

### (a) `trung_tinh` — Kể chuyện (chiếm ~80% nội dung, quan trọng nhất)
- Cách đọc: bình thản, rõ ràng, tốc độ vừa, ấm nhẹ, **không** lên xuống kịch tính.
- Đây là "giọng gốc" — hãy thu clip này **đầu tiên** để làm mốc cho các register khác.

> Buổi sáng, sương còn đọng trên những tán lá. Con đường nhỏ dẫn ra bến sông
> vắng lặng, chỉ có tiếng nước chảy đều đều bên bờ. Ông lão chậm rãi bước đi,
> tay khẽ vịn vào chiếc gậy tre đã mòn.

### (b) `doi_thoai` — Đối thoại
- Cách đọc: sinh động, năng lượng cao hơn, ngữ điệu lên xuống rõ, nhịp nhanh hơn chút.

> — Cậu đi đâu mà vội thế? — Tôi phải ra ga cho kịp chuyến tàu chiều!
> — Trời ơi, giờ này còn chạy nữa à, đợi tôi với!

### (c) `tinh_cam` — Tình cảm
- Cách đọc: ấm, chậm hơn, mềm, có sức nặng cảm xúc, hơi trầm xuống cuối câu.

> Mẹ ơi, con về rồi đây. Bao nhiêu năm xa nhà, con chưa một lần quên dáng mẹ
> ngồi bên hiên, chờ con mỗi buổi chiều tà. Giờ đứng trước cửa, lòng con nghẹn
> lại, chẳng nói nên lời.

### (d) `goi_cam` — Thân mật / gợi cảm
- Cách đọc: trầm, nhẹ, chậm, thì thầm gần mic, nhiều khoảng nghỉ, âm lượng mềm.

> Lại đây, ngồi gần một chút. Đừng vội, cứ để đêm trôi thật chậm. Tôi muốn nghe
> tiếng thở khẽ bên tai, muốn giữ khoảnh khắc này thật lâu.

> **Tùy chọn mở rộng** (thu sau nếu cần): `kich_tinh` (căng, hồi hộp), `vui_tuoi` (tươi, rộn ràng).
> Cứ bắt đầu với 4 register lõi cho gọn.

## 3. Mẹo giữ danh tính giọng đồng nhất (phần quan trọng nhất)

Đây là điều quyết định việc app chuyển sắc thái nghe có còn là "một người" hay không:

1. **Thu cả 4 register trong CÙNG một buổi**, cùng mic, cùng khoảng cách, cùng mức gain,
   cùng căn phòng. Khác buổi/khác setup → giọng lệch nhau.
2. **Neo về giọng gốc**: đọc clip `trung_tinh` trước, rồi *điều biến cảm xúc từ giọng gốc đó*.
   Giữa mỗi register, đọc lại một câu trung tính để "về mốc".
3. **Đổi cách đọc, đừng đổi giọng nền**: thay đổi *năng lượng, tốc độ, độ mềm, độ ấm* —
   **không** đổi cao độ/âm sắc cơ bản của bạn. Nếu register gợi cảm bạn hạ giọng xuống
   hẳn một quãng, danh tính sẽ nghe như người khác.
4. **Đồng đều âm lượng** giữa các clip, để app chuyển register không bị nhảy to/nhỏ.

## 4. Xử lý sau khi thu

- Cắt bỏ khoảng lặng thừa đầu/cuối; chọn đoạn 6–8 giây **liền mạch, không vấp**.
- Chuẩn hóa âm lượng nhẹ nhàng cho các clip đồng đều. **Đừng** xử lý quá tay
  (VieNeu đã có `denoise=True` lo phần nhiễu còn sót).
- Lưu WAV mono, đặt tên rõ theo register:
  `trung_tinh.wav`, `doi_thoai.wav`, `tinh_cam.wav`, `goi_cam.wav`.

## 5. Kiểm thử (vòng lặp nghe – chỉnh)

Sau khi thu, clone từng clip rồi **tổng hợp CÙNG một câu thử** bằng cả 4 register, so sánh:

1. **Danh tính có nhất quán không?** — nghe như cùng một người ở cả 4 clip chứ?
   Nếu lệch → thu lại với giọng gốc ổn định hơn, hoặc dùng tính năng *blend*
   (khóa `speaker_emb` từ clip `trung_tinh`, chỉ mượn ngữ điệu từ các clip kia).
2. **Mỗi register có đúng sắc thái không?** — đối thoại có sinh động hơn, gợi cảm có mềm/chậm hơn?
3. **Có artifact/rè/méo không?** — nếu có, thường do clip mẫu chưa sạch → thu lại.

Chỉnh register nào yếu nhất trước, thu lại chỉ clip đó (nhớ cùng setup).

---

### Tóm tắt 1 dòng
Thu 4 clip 6–8 giây, **một buổi – một setup**, đọc đúng sắc thái từng register,
giữ giọng nền không đổi, rồi nghe thử chéo để chắc "vẫn là một người".
