# Local Setup Guide (Windows - No Docker)

## 1. Install Tesseract OCR
1. Run: `C:\Users\LENOVO\Downloads\tesseract-ocr-w64-setup-5.5.0.20241111.exe`
2. **IMPORTANT**: Check "French language pack (fra)" during installation
3. Install to: `C:\Program Files\Tesseract-OCR`
4. Add to PATH or update `.env` with: `TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe`

## 2. Install Poppler (for pdf2image)
1. Extract `C:\Users\LENOVO\Downloads\Release-25.12.0-0.zip`
2. Move to: `C:\Program Files\poppler-25.12.0\`
3. Add to PATH: `C:\Program Files\poppler-25.12.0\Library\bin`

## 3. Install PostgreSQL 15
1. Download: https://www.postgresql.org/download/windows/
2. Install with:
   - Password: `secret`
   - Port: `5432`
3. Create database:
   ```bash
   psql -U postgres
   CREATE DATABASE magriplast;
   CREATE USER magriplast WITH PASSWORD 'secret';
   GRANT ALL PRIVILEGES ON DATABASE magriplast TO magriplast;
   \q
   ```

## 4. Install Redis
Option A - Memurai (Recommended for Windows):
1. Download: https://www.memurai.com/get-memurai
2. Install and start service

Option B - Redis for Windows:
1. Download: https://github.com/tporadowski/redis/releases
2. Extract to: `C:\Redis`
3. Run: `C:\Redis\redis-server.exe`

## 5. Setup MinIO (Object Storage)
1. Download: https://dl.min.io/server/minio/release/windows-amd64/minio.exe
2. Create folder: `C:\minio-data`
3. Run MinIO:
   ```bash
   minio.exe server C:\minio-data --console-address ":9001"
   ```
4. Access console: http://localhost:9001
   - Username: `minioadmin`
   - Password: `minioadmin`
5. Create bucket named: `magriplast-documents`

## 6. Update Environment Variables

Update `server\.env` file with correct paths:
```env
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
```

## 7. Initialize Database
```bash
cd D:\house_md\Magriplast_comparator-main\server
alembic upgrade head
```

## 8. Start Services (4 separate terminals)

### Terminal 1 - Redis
```bash
redis-server
# or if using Memurai, it runs as a service
```

### Terminal 2 - MinIO
```bash
minio.exe server C:\minio-data --console-address ":9001"
```

### Terminal 3 - Backend API
```bash
cd D:\house_md\Magriplast_comparator-main\server
uvicorn app.main:app --reload --port 8000
```

### Terminal 4 - Celery Worker (PDF Processing)
```bash
cd D:\house_md\Magriplast_comparator-main\server
celery -A app.core.celery_app.celery_app worker -Q pdf_processing -c 4 --loglevel=info --pool=solo
```

### Terminal 5 - Celery Worker (LLM Tasks)
```bash
cd D:\house_md\Magriplast_comparator-main\server
celery -A app.core.celery_app.celery_app worker -Q llm_tasks -c 10 --loglevel=info --pool=solo
```

**Note**: Use `--pool=solo` on Windows as Celery has issues with default pool on Windows.

## 9. Start Frontend
```bash
cd D:\house_md\Magriplast_comparator-main\frontend
npm install
npm run dev
```

## Access Points
- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs
- MinIO Console: http://localhost:9001

## Quick Test
1. Open http://localhost:8000/docs
2. Try the health check endpoint
3. Upload a test PDF through the frontend
