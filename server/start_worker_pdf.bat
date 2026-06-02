@echo off
echo Starting Celery Worker - PDF Processing...
cd /d D:\house_md\Magriplast_comparator-main\server
celery -A app.core.celery_app.celery_app worker -Q pdf_processing -c 4 --loglevel=info --pool=solo
pause
