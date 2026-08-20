#!/usr/bin/env bash
# Chạy app với giọng VieNeu-TTS (offline, tự nhiên hơn Piper). Lần đầu tải model.
set -e
cd "$(dirname "$0")"
if [ ! -d ".venv" ]; then python3 -m venv .venv; fi
source .venv/bin/activate
pip install -q -r requirements.txt || true
pip install -q vieneu
# torch (CPU) cho tính năng nhân bản giọng (voice cloning)
pip install -q torch torchaudio --index-url https://download.pytorch.org/whl/cpu
export TTS_PROVIDER=vieneu
# export VIENEU_VOICE="Trúc Ly"   # bỏ dấu # để chọn giọng cụ thể
# Ổn định giọng: 0.8 là mức ổn định nhất cho v3 Turbo (chống trôi giọng giữa các câu).
# Hạ xuống 0.7 / 0.6 nếu vẫn muốn cố định hơn nữa (đổi lại giọng đọc "đều" hơn).
export VIENEU_TEMPERATURE=0.8
# (Tùy chọn) Bật phân loại sắc thái tình cảm/gợi cảm bằng LLM (rẻ, cache 1 lần/sách).
# Không đặt thì heuristic đối thoại vẫn chạy, phần còn lại đọc phẳng.
# export ANTHROPIC_API_KEY="sk-ant-..."
echo ""
echo "Giọng: VieNeu-TTS (offline). Mở: http://127.0.0.1:8000"
echo "Lần đầu sẽ tải model VieNeu (~vài trăm MB) — cần mạng một lần."
echo ""
cd backend
exec uvicorn app:app --host 127.0.0.1 --port 8000
