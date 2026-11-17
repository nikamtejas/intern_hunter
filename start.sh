#!/usr/bin/env bash
# Intern Hunter — one-command start (macOS / Linux)
set -e
cd "$(dirname "$0")/backend"
if [ ! -d .venv ]; then
  echo "Creating Python virtual environment..."
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt
[ -f .env ] || cp .env.example .env
if [ ! -d ../frontend/dist ] && command -v npm >/dev/null; then
  (cd ../frontend && npm install && npm run build)
fi
echo ""
echo "  Intern Hunter running at  http://localhost:8000"
echo ""
( sleep 2; (command -v open >/dev/null && open http://localhost:8000) || (command -v xdg-open >/dev/null && xdg-open http://localhost:8000) || true ) &
exec uvicorn app.main:app --host 127.0.0.1 --port 8000
