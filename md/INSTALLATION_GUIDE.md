# Quick Installation Checklist

## ✅ Already Installed
- [x] Python 3.12 + all packages
- [x] Tesseract OCR with French language pack at C:\Program Files\Tesseract-OCR

## 📥 Still Need to Install

### 1. PostgreSQL 15
**Download:** https://www.enterprisedb.com/downloads/postgres-postgresql-downloads
- Choose: PostgreSQL 15.x for Windows x86-64
- During installation:
  - Password: `secret` (or remember to update .env)
  - Port: `5432` (default)
  - Locale: Default
- After installation, open Command Prompt and run:
  ```bash
  psql -U postgres
  # Enter password: secret
  CREATE DATABASE magriplast;
  \q
  ```

### 2. Redis for Windows
**Option A - Memurai (Recommended, easier):**
- Download: https://www.memurai.com/get-memurai
- Install and it runs as a Windows service automatically

**Option B - Redis Windows Port:**
- Download: https://github.com/tporadowski/redis/releases/latest
- Download: `Redis-x64-5.0.14.1.zip` (or latest)
- Extract to: `C:\Redis`
- To start: Open CMD and run `C:\Redis\redis-server.exe`

### 3. MinIO (Object Storage)
**Download:** https://dl.min.io/server/minio/release/windows-amd64/minio.exe
- Save to: `C:\minio\minio.exe`
- Create data folder: `C:\minio-data`
- To start: Open CMD and run:
  ```bash
  cd C:\minio
  minio.exe server C:\minio-data --console-address ":9001"
  ```
- First time: Open http://localhost:9001
  - Login: minioadmin / minioadmin
  - Create bucket: `magriplast-documents`

### 4. Poppler (for pdf2image)
- Extract: `C:\Users\LENOVO\Downloads\Release-25.12.0-0.zip`
- Move folder to: `C:\poppler`
- Add to System PATH: `C:\poppler\Library\bin`
  - Right-click "This PC" → Properties → Advanced System Settings
  - Environment Variables → System Variables → Path → Edit → New
  - Add: `C:\poppler\Library\bin`

## 🚀 After Installation - Start Services

### Terminal 1: Redis
```bash
# If using Memurai, it's already running as a service
# If using Redis zip, run:
C:\Redis\redis-server.exe
```

### Terminal 2: MinIO
```bash
cd C:\minio
minio.exe server C:\minio-data --console-address ":9001"
```

### Terminal 3: Initialize Database (ONE TIME ONLY)
```bash
cd D:\house_md\Magriplast_comparator-main\server
alembic upgrade head
```

### Terminal 4: Backend API
```bash
cd D:\house_md\Magriplast_comparator-main\server
uvicorn app.main:app --reload --port 8000
```

### Terminal 5: Celery Worker - PDF Processing
```bash
cd D:\house_md\Magriplast_comparator-main\server
celery -A app.core.celery_app.celery_app worker -Q pdf_processing -c 4 --loglevel=info --pool=solo
```

### Terminal 6: Celery Worker - LLM Tasks
```bash
cd D:\house_md\Magriplast_comparator-main\server
celery -A app.core.celery_app.celery_app worker -Q llm_tasks -c 10 --loglevel=info --pool=solo
```

### Terminal 7: Frontend
```bash
cd D:\house_md\Magriplast_comparator-main\frontend
npm install
npm run dev
```

## 🌐 Access URLs
- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API Documentation: http://localhost:8000/docs
- MinIO Console: http://localhost:9001

## 🧪 Quick Test
1. Open http://localhost:8000/docs
2. Try the `/api/v1/health` endpoint (if it exists)
3. Upload a test PDF through the frontend at http://localhost:5173

## ⚠️ Common Issues

**Issue: "Tesseract not found"**
- Solution: Already fixed in .env file

**Issue: "Cannot connect to database"**
- Solution: Make sure PostgreSQL service is running
- Check Windows Services → postgresql-x64-15

**Issue: "Redis connection refused"**
- Solution: Make sure Redis/Memurai is running
- Check Windows Services → Memurai (if using Memurai)

**Issue: "Celery won't start on Windows"**
- Solution: Always use `--pool=solo` flag on Windows

**Issue: "pdf2image error"**
- Solution: Make sure Poppler bin folder is in PATH
- Restart terminal after adding to PATH
