@echo off
REM Tai giong tieng Viet Piper (vais1000-medium, ~63MB) vao thu muc voices\
set DIR=%~dp0voices
if not exist "%DIR%" mkdir "%DIR%"
set BASE=https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/vi/vi_VN/vais1000/medium
echo Dang tai mo hinh giong vao %DIR% ...
curl -L --fail -o "%DIR%\vi_VN-vais1000-medium.onnx"      "%BASE%/vi_VN-vais1000-medium.onnx"
curl -L --fail -o "%DIR%\vi_VN-vais1000-medium.onnx.json" "%BASE%/vi_VN-vais1000-medium.onnx.json"
echo Xong. Khoi dong lai server de dung giong.
