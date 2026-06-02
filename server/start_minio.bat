@echo off
echo Starting MinIO Server...
echo Make sure you have minio.exe downloaded!
echo.
set MINIO_ROOT_USER=minioadmin
set MINIO_ROOT_PASSWORD=minioadmin
set MINIO_STORAGE_CLASS_STANDARD=EC:0
minio.exe server D:\house_md\Magriplast_comparator-main\minio-data --console-address ":9001"
pause
