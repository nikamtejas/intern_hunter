@echo off
REM Intern Hunter - one-click start (Windows)
cd /d "%~dp0backend"
if not exist .venv (
  echo Creating Python virtual environment...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
if not exist .env copy .env.example .env >nul
if not exist ..\frontend\dist (
  where npm >nul 2>nul && (pushd ..\frontend & call npm install & call npm run build & popd)
)
echo.
echo   Intern Hunter running at  http://localhost:8000
echo.
start "" http://localhost:8000
uvicorn app.main:app --host 127.0.0.1 --port 8000
