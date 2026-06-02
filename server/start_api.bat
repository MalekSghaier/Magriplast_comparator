@echo off
echo Starting Magriplast Backend API...
cd /d D:\house_md\Magriplast_comparator-main\server
uvicorn app.main:app --reload --port 8000
pause
