@echo off
cd /d "%~dp0"
if not exist ".venv" ( python -m venv .venv )
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
pip install -q vieneu
REM torch (CPU) can cho tinh nang nhan ban giong (voice cloning)
pip install -q torch torchaudio --index-url https://download.pytorch.org/whl/cpu
set TTS_PROVIDER=vieneu
REM set VIENEU_VOICE=Truc Ly    &REM bo REM de chon giong cu the
REM On dinh giong: 0.8 la muc on dinh nhat cho v3 Turbo (chong troi giong giua cac cau).
REM Ha xuong 0.7 / 0.6 neu van muon co dinh hon nua.
set VIENEU_TEMPERATURE=0.8
REM (Tuy chon) Bat phan loai sac thai tinh cam/goi cam bang LLM (re, cache 1 lan/sach).
REM Khong dat thi heuristic doi thoai van chay, phan con lai doc phang.
REM set ANTHROPIC_API_KEY=sk-ant-...
echo.
echo Giong: VieNeu-TTS (offline). Mo: http://127.0.0.1:8000
echo Lan dau se tai model VieNeu (~vai tram MB) - can mang mot lan.
echo.
cd backend
uvicorn app:app --host 127.0.0.1 --port 8000
