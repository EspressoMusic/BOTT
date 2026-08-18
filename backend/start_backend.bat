@echo off
cd /d C:\Users\Nirhdhd\BOTT\backend
"C:\Users\Nirhdhd\BOTT\backend\venv\Scripts\python.exe" -m uvicorn app.main:app --reload --reload-dir app >> C:\Users\Nirhdhd\BOTT\backend\backend_stdout.log 2>> C:\Users\Nirhdhd\BOTT\backend\backend_stderr.log
