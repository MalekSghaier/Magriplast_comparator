@echo off
echo Starting Celery Worker - LLM Tasks...
cd /d D:\house_md\Magriplast_comparator-main\server
celery -A app.core.celery_app.celery_app worker -Q llm_tasks -c 10 --loglevel=info --pool=solo
pause
