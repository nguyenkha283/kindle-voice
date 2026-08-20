#!/usr/bin/env bash
# Tải giọng tiếng Việt Piper (vais1000-medium, ~63MB) về thư mục voices/
set -e
DIR="$(cd "$(dirname "$0")" && pwd)/voices"
mkdir -p "$DIR"
BASE="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/vi/vi_VN/vais1000/medium"
echo "Đang tải mô hình giọng vào $DIR ..."
curl -L --fail -o "$DIR/vi_VN-vais1000-medium.onnx"      "$BASE/vi_VN-vais1000-medium.onnx"
curl -L --fail -o "$DIR/vi_VN-vais1000-medium.onnx.json" "$BASE/vi_VN-vais1000-medium.onnx.json"
echo "Xong. Khởi động lại server để dùng giọng."
