#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -d ".venv" ]; then
  echo "Tạo môi trường ảo .venv ..."
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt || pip install -q fastapi "uvicorn[standard]" EbookLib beautifulsoup4 python-multipart
echo ""
echo "Mở trình duyệt tại: http://127.0.0.1:8000"
echo ""
cd backend
exec uvicorn app:app --host 127.0.0.1 --port 8000
