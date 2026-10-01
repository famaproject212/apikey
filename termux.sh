#!/data/data/com.termux/files/usr/bin/bash
set -e
pkg update -y
pkg install python -y
pip install --upgrade pip
pip install -r requirements.txt
cp -n .env.example .env || true
echo "Edit .env lalu jalankan:"
echo "uvicorn main:app --host 0.0.0.0 --port 8000"
