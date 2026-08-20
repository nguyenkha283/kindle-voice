@echo off
cd /d "%~dp0"
if not exist ".venv" (
  echo Tao moi truong ao .venv ...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
echo.
echo Mo trinh duyet tai: http://127.0.0.1:8000
echo.
cd backend
uvicorn app:app --host 127.0.0.1 --port 8000
