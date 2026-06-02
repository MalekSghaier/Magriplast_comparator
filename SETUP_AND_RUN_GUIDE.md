# Magriplast Document Processing System - Complete Setup & Run Guide

## 📋 Table of Contents
1. [Prerequisites Installation](#prerequisites-installation)
2. [Project Setup](#project-setup)
3. [How to Start the Application](#how-to-start-the-application)
4. [Access URLs](#access-urls)
5. [Troubleshooting](#troubleshooting)

---

## 🔧 Prerequisites Installation

### 1. Python 3.12
- Already installed at: `C:\Users\LENOVO\AppData\Local\Programs\Python\Python312`
- ✅ All Python packages installed via `pip install -r requirements.txt`

### 2. Tesseract OCR with French Language Pack
- **Installed at:** `C:\Program Files\Tesseract-OCR`
- **Version:** 5.5.0
- **Language Pack:** French (fra) ✅
- **Verify installation:**
  ```bash
  "C:\Program Files\Tesseract-OCR\tesseract.exe" --version
  "C:\Program Files\Tesseract-OCR\tesseract.exe" --list-langs
  ```

### 3. PostgreSQL 16
- **Installed:** PostgreSQL 16
- **Database Name:** `magriplast`
- **Username:** `postgres`
- **Password:** `23044943`
- **Port:** `5432` (default)
- **Status:** ✅ Running and configured

### 4. Redis
- **Installed at:** `C:\Redis`
- **Version:** 5.0.14.1
- **Port:** `6379` (default)
- **Status:** ✅ Running

### 5. MinIO (Object Storage)
- **Installed at:** `C:\minio\minio.exe`
- **Data folder:** `C:\minio-data`
- **Port:** `9000` (API), `9001` (Console)
- **Credentials:** `minioadmin` / `minioadmin`
- **Bucket:** `magriplast-documents` ✅

### 6. Node.js & npm
- **Status:** ✅ Installed
- **Frontend dependencies:** ✅ Installed via `npm install`

---

## ⚙️ Project Setup

### Configuration Files

#### Backend Configuration (`.env`)
Location: `D:\house_md\Magriplast_comparator-main\server\.env`

```env
DEBUG=true
APP_NAME=Magriplast Document Processing
API_PREFIX=/api/v1

# Database
DATABASE_URL=postgresql+asyncpg://postgres:23044943@localhost:5432/magriplast

# Redis / Celery
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1

# Storage (MinIO)
STORAGE_ENDPOINT_URL=http://localhost:9000
STORAGE_ACCESS_KEY=minioadmin
STORAGE_SECRET_KEY=minioadmin
STORAGE_BUCKET_NAME=magriplast-documents

# OCR / LLM fallbacks
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
TESSERACT_LANGUAGE=fra
GOOGLE_DOCAI_ENABLED=false
OPENAI_API_KEY=
```

#### Database Tables
- ✅ Auto-created on first API startup (DEBUG=true mode)
- Tables: `jobs`, `documents`, `line_items`, `match_results`, `audit_logs`, `supplier_profiles`, `word_dictionary`

---

## 🚀 How to Start the Application

You need **5 terminal windows** running simultaneously:

### Terminal 1: MinIO (Object Storage)
```bash
C:\minio\minio.exe server C:\minio-data --console-address ":9001"
```
**Keep this running!**

---

### Terminal 2: Backend API (FastAPI)
```bash
cd D:\house_md\Magriplast_comparator-main\server
uvicorn app.main:app --reload --port 8000
```
**Expected output:**
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Application startup complete.
```
**Keep this running!**

---

### Terminal 3: Celery Worker - PDF Processing
```bash
cd D:\house_md\Magriplast_comparator-main\server
celery -A app.core.celery_app.celery_app worker -Q pdf_processing -c 4 --loglevel=info --pool=solo
```
**Expected output:**
```
[2026-05-20 19:23:58,726: INFO/MainProcess] celery@DESKTOP-VI3GQDQ ready.
```
**Keep this running!**

---

### Terminal 4: Celery Worker - LLM Tasks
```bash
cd D:\house_md\Magriplast_comparator-main\server
celery -A app.core.celery_app.celery_app worker -Q llm_tasks -c 10 --loglevel=info --pool=solo
```
**Expected output:**
```
[2026-05-20 19:24:45,066: INFO/MainProcess] celery@DESKTOP-VI3GQDQ ready.
```
**Keep this running!**

---

### Terminal 5: Frontend (React + Vite)
```bash
cd D:\house_md\Magriplast_comparator-main\frontend
npm run dev
```
**Expected output:**
```
VITE v5.4.21  ready in 475 ms
➜  Local:   http://localhost:3000/
```
**Keep this running!**

---

## 🌐 Access URLs

Once all services are running:

| Service | URL | Credentials |
|---------|-----|-------------|
| **Frontend (Main App)** | http://localhost:3000 | - |
| **Backend API** | http://localhost:8000 | - |
| **API Documentation** | http://localhost:8000/api/v1/docs | - |
| **Health Check** | http://localhost:8000/health | - |
| **MinIO Console** | http://localhost:9001 | minioadmin / minioadmin |

---

## 📝 Quick Start Checklist

Before starting the application each time:

- [ ] PostgreSQL service is running (check Windows Services)
- [ ] Redis is running (should auto-start if installed as service)
- [ ] All 5 terminals are open and ready

Then start in this order:
1. ✅ MinIO (Terminal 1)
2. ✅ Backend API (Terminal 2) - wait for "Application startup complete"
3. ✅ Celery Worker PDF (Terminal 3) - wait for "ready"
4. ✅ Celery Worker LLM (Terminal 4) - wait for "ready"
5. ✅ Frontend (Terminal 5)

---

## 🛠️ Troubleshooting

### Issue: "Redis connection refused"
**Solution:**
```bash
# Check if Redis is running
netstat -ano | findstr :6379

# If not running, start Redis
C:\Redis\redis-server.exe
```

---

### Issue: "Database connection error"
**Solution:**
```bash
# Check PostgreSQL service
services.msc
# Look for "postgresql-x64-16" and ensure it's running

# Test connection
psql -U postgres -d magriplast
```

---

### Issue: "MinIO bucket not found"
**Solution:**
1. Open http://localhost:9001
2. Login: minioadmin / minioadmin
3. Go to "Buckets" → "Create Bucket"
4. Name: `magriplast-documents`
5. Click "Create Bucket"

---

### Issue: "Tesseract not found"
**Solution:**
Check `.env` file has correct path:
```env
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
```

---

### Issue: "Celery won't start"
**Solution:**
Always use `--pool=solo` flag on Windows:
```bash
celery -A app.core.celery_app.celery_app worker -Q pdf_processing -c 4 --loglevel=info --pool=solo
```

---

### Issue: "Port already in use"
**Solution:**
```bash
# Find process using port 8000
netstat -ano | findstr :8000

# Kill process (replace PID with actual process ID)
taskkill /PID <PID> /F
```

---

## 📂 Project Structure

```
Magriplast_comparator-main/
├── server/                          # Backend (Python/FastAPI)
│   ├── app/
│   │   ├── api/                     # API endpoints
│   │   ├── core/                    # Config, database, celery
│   │   ├── models/                  # SQLAlchemy models
│   │   ├── schemas/                 # Pydantic schemas
│   │   ├── services/                # Business logic
│   │   ├── utils/                   # Helper functions
│   │   ├── workers/                 # Celery workers
│   │   └── main.py                  # FastAPI app entry
│   ├── alembic/                     # Database migrations
│   ├── tests/                       # Unit tests
│   ├── .env                         # Environment variables
│   ├── requirements.txt             # Python dependencies
│   └── docker-compose.yml           # Docker setup (not used)
│
├── frontend/                        # Frontend (React/Vite)
│   ├── src/
│   │   ├── api/                     # API client
│   │   ├── components/              # React components
│   │   ├── hooks/                   # Custom hooks
│   │   ├── pages/                   # Page components
│   │   ├── utils/                   # Helper functions
│   │   ├── App.jsx                  # Main app component
│   │   └── main.jsx                 # Entry point
│   ├── public/                      # Static assets
│   ├── package.json                 # Node dependencies
│   └── vite.config.js               # Vite configuration
│
├── md/                              # Documentation
│   ├── exution.md                   # Execution guide
│   └── magriplast_architecture.md   # Architecture docs
│
└── minio-data/                      # MinIO data storage
```

---

## 🎯 System Architecture Overview

### Processing Pipeline
1. **Layer 0 - Ingestion:** Upload PDF via frontend
2. **Layer 1 - PDF Analysis:** Detect native vs scanned pages
3. **Layer 2 - Preprocessing:** Clean scanned images (OCR prep)
4. **Layer 3 - Classification:** Identify document type (BC/BL/FACTURE)
5. **Layer 4 - Page Grouping:** Group multi-page documents
6. **Layer 5 - Extraction:** Extract data using OCR/templates
7. **Layer 6 - Normalization:** Fix OCR errors, normalize numbers
8. **Layer 7 - Validation:** Validate extracted data
9. **Layer 8 - Matching:** 3-way matching (BC ↔ BL ↔ FACTURE)
10. **Layer 9 - Output:** Generate results and audit logs

### Technology Stack
- **Backend:** Python 3.12, FastAPI, SQLAlchemy, Celery
- **Frontend:** React 18, Vite, TailwindCSS
- **Database:** PostgreSQL 16
- **Queue:** Redis 7
- **Storage:** MinIO (S3-compatible)
- **OCR:** Tesseract 5 (French), Google Document AI (fallback)
- **PDF Processing:** PyMuPDF, pdf2image, OpenCV

---

## 📞 Support

For issues or questions:
1. Check the [Troubleshooting](#troubleshooting) section
2. Review logs in the terminal windows
3. Check API documentation at http://localhost:8000/api/v1/docs

---

## 🔄 Stopping the Application

To stop all services:
1. Press `Ctrl+C` in each terminal window
2. Confirm shutdown for each service
3. Close all terminal windows

**Note:** PostgreSQL and Redis (if installed as services) will continue running in the background.

---

## 📅 Last Updated
May 20, 2026

---

**🎉 Setup Complete! Your Magriplast Document Processing System is ready to use.**
///////////////////////////////////////////////////////////////////////////////////////
*******************************************************************************************
# Terminal 1 - MinIO
C:\minio\minio.exe server C:\minio-data --console-address ":9001"

# Terminal 2 - Backend API
cd D:\house_md\Magriplast_comparator-main\server
uvicorn app.main:app --reload --port 8000

# Terminal 3 - Celery Worker (PDF)
cd D:\house_md\Magriplast_comparator-main\server
celery -A app.core.celery_app.celery_app worker -Q pdf_processing -c 4 --loglevel=info --pool=solo

# Terminal 4 - Celery Worker (LLM)
cd D:\house_md\Magriplast_comparator-main\server
celery -A app.core.celery_app.celery_app worker -Q llm_tasks -c 10 --loglevel=info --pool=solo

# Terminal 5 - Frontend
cd D:\house_md\Magriplast_comparator-main\frontend
npm run dev
*******************************************************************************************
///////////////////////////////////////////////////////////////////////////////////////