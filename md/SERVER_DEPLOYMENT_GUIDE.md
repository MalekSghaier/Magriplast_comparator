# Magriplast Server Deployment Guide
## khiari mohamed 

Target server:
- IP: `5.199.136.2`
- SSH user: `root`
- Access method: PuTTY
- Backend process manager: `pm2`
- Frontend web server: `nginx`
- App path used in this guide: `/opt/magriplast/current`



## 1. Connect With PuTTY

1. Open PuTTY.
2. Host Name: `5.199.136.2`
3. Port: `22`
4. Connection type: `SSH`
5. Click `Open`.
6. Login as: `root`
7. Enter the server password when prompted.

## 2. Inspect Before Changing Anything

Run these commands first. They do not modify the server and help avoid breaking other hosted apps.

```bash
whoami
hostname
pwd
uname -a
lsb_release -a 2>/dev/null || cat /etc/os-release
uptime
date
```

Check disk, memory, and CPU:

```bash
df -h
free -h
nproc
top -bn1 | head -40
```

Check existing services:

```bash
systemctl --type=service --state=running
pm2 list || true
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}' || true
```

Check ports already used by other apps:

```bash
ss -tulpn
ss -tulpn | grep -E ':80|:443|:8000|:9000|:9001|:5432|:6379' || true
```

Check Nginx before editing:

```bash
nginx -v 2>/dev/null || true
ls -la /etc/nginx/sites-available /etc/nginx/sites-enabled 2>/dev/null || true
nginx -T 2>/dev/null | less
```

Check existing databases and Redis:

```bash
systemctl status postgresql --no-pager 2>/dev/null || true
systemctl status redis-server --no-pager 2>/dev/null || true
sudo -u postgres psql -c '\l' 2>/dev/null || true
redis-cli ping 2>/dev/null || true
```

Only continue after confirming these ports are available or intentionally used: ( else a5tar prts o5rin far8in)

- `8000`: backend API, bound to `127.0.0.1` only
- `9000`: MinIO API, bound to `127.0.0.1` only
- `9001`: MinIO console, bound to `127.0.0.1` only
- `5432`: PostgreSQL
- `6379`: Redis
- `80`: Nginx public HTTP

## 3. Install System Packages

For Ubuntu/Debian:

```bash
apt update
apt install -y git curl ca-certificates build-essential \
  python3 python3-venv python3-pip python3-dev \
  postgresql postgresql-contrib redis-server nginx \
  tesseract-ocr tesseract-ocr-fra poppler-utils \
  libgl1 libglib2.0-0 libsm6 libxext6 libxrender1
```

Install Node.js LTS and PM2:

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt install -y nodejs
npm install -g pm2
node -v
npm -v
pm2 -v
```

Enable base services:

```bash
systemctl enable --now postgresql
systemctl enable --now redis-server
systemctl enable --now nginx
```

## 4. Create Isolated App Directory

```bash
mkdir -p /opt/magriplast
cd /opt/magriplast
```

Copy the project to the server using one of these methods.

Option A, from Git:

```bash
git clone <YOUR_REPOSITORY_URL> current
cd /opt/magriplast/current
```

Option B, from Windows using `pscp`: wala `wincsp` 

```powershell
pscp -r D:\house_md\Magriplast_comparator-main root@5.199.136.2:/opt/magriplast/current
```

After copying:

```bash
cd /opt/magriplast/current
ls -la
ls -la server frontend
```

## 5. PostgreSQL Database

Use a dedicated database and user so other apps are not affected.

Generate a strong DB password: ( 5alih dima metdahrkto deja bech t7to fo .env fi link ta3 l db wala ken t7eb testa3ml l db 3adya deja sab postgresql ena modpasha kima l local " 23044943"  )

```bash
openssl rand -base64 32
```

Create the database. Replace `CHANGE_DB_PASSWORD` with your generated password.

```bash
sudo -u postgres psql
```

Inside `psql`:

```sql
CREATE USER magriplast_user WITH PASSWORD 'CHANGE_DB_PASSWORD';
CREATE DATABASE magriplast OWNER magriplast_user;
\c magriplast
GRANT ALL ON SCHEMA public TO magriplast_user;
ALTER SCHEMA public OWNER TO magriplast_user;
\q
```

Inspect:

```bash
sudo -u postgres psql -c '\l'
sudo -u postgres psql -d magriplast -c '\dt'
```

## 6. MinIO Object Storage

Install MinIO server:

```bash
curl -fsSL https://dl.min.io/server/minio/release/linux-amd64/minio -o /usr/local/bin/minio
chmod +x /usr/local/bin/minio
minio --version
```

Create a dedicated data directory and credentials:

```bash
mkdir -p /var/lib/magriplast-minio
chmod 700 /var/lib/magriplast-minio
openssl rand -hex 16
openssl rand -hex 32
```

Create the MinIO environment file:

```bash
nano /etc/default/magriplast-minio
```

Paste this, replacing the two credential values:

```env
MINIO_ROOT_USER=CHANGE_MINIO_ACCESS_KEY
MINIO_ROOT_PASSWORD=CHANGE_MINIO_SECRET_KEY
MINIO_VOLUMES=/var/lib/magriplast-minio
MINIO_OPTS=--address 127.0.0.1:9000 --console-address 127.0.0.1:9001
```

Create the systemd service:

```bash
nano /etc/systemd/system/magriplast-minio.service
```

Paste:

```ini
[Unit]
Description=Magriplast MinIO
After=network-online.target
Wants=network-online.target

[Service]
EnvironmentFile=/etc/default/magriplast-minio
ExecStart=/usr/local/bin/minio server $MINIO_VOLUMES $MINIO_OPTS
Restart=always
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

Start and inspect:

```bash
systemctl daemon-reload
systemctl enable --now magriplast-minio
systemctl status magriplast-minio --no-pager
ss -tulpn | grep -E ':9000|:9001'
```

Install the MinIO client and create the bucket:

```bash
curl -fsSL https://dl.min.io/client/mc/release/linux-amd64/mc -o /usr/local/bin/mc
chmod +x /usr/local/bin/mc
mc alias set magriplast-local http://127.0.0.1:9000 CHANGE_MINIO_ACCESS_KEY CHANGE_MINIO_SECRET_KEY
mc mb --ignore-existing magriplast-local/magriplast-documents
mc ls magriplast-local
```

To access the MinIO console safely from your PC, use an SSH tunnel instead of opening port `9001` publicly:

```powershell
putty.exe -ssh root@5.199.136.2 -L 9001:127.0.0.1:9001
```

Then open `http://127.0.0.1:9001` on your PC.

## 7. Backend Environment

Create the Python virtual environment:

```bash
cd /opt/magriplast/current/server
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip wheel setuptools
pip install -r requirements.txt
pip install "python-jose[cryptography]" "passlib[bcrypt]"
```

The last command is needed because the backend imports `jose` and `passlib` for JWT/password handling.

Generate app secrets:

```bash
openssl rand -hex 32
```

Create the backend `.env`:

```bash
nano /opt/magriplast/current/server/.env
```

Paste this and replace all `CHANGE_*` values:

```env
DEBUG=false
APP_NAME=Magriplast Document Processing
API_PREFIX=/api/v1

DATABASE_URL=postgresql+asyncpg://magriplast_user:CHANGE_DB_PASSWORD@127.0.0.1:5432/magriplast

REDIS_URL=redis://127.0.0.1:6379/0
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/1

STORAGE_ENDPOINT_URL=http://127.0.0.1:9000
STORAGE_ACCESS_KEY=CHANGE_MINIO_ACCESS_KEY
STORAGE_SECRET_KEY=CHANGE_MINIO_SECRET_KEY
STORAGE_BUCKET_NAME=magriplast-documents
STORAGE_REGION=us-east-1

TESSERACT_CMD=/usr/bin/tesseract
TESSERACT_LANGUAGE=fra

GOOGLE_DOCAI_ENABLED=false
GOOGLE_DOCAI_PROJECT_ID=
GOOGLE_DOCAI_PROCESSOR_ID=
GOOGLE_APPLICATION_CREDENTIALS=

OPENAI_API_KEY=
LLM_MODEL=gpt-4o
LLM_MAX_TOKENS=1500
LLM_TEMPERATURE=0.0

GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.5-flash
USE_PARALLEL_VISION=true

SECRET_KEY=CHANGE_SECRET_KEY
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
```

Protect the env file:

```bash
chmod 600 /opt/magriplast/current/server/.env
```

Run DB migrations:

```bash
cd /opt/magriplast/current/server
source .venv/bin/activate
alembic upgrade head
sudo -u postgres psql -d magriplast -c '\dt'
```

Create the MinIO bucket through the app helper too:

```bash
cd /opt/magriplast/current/server
source .venv/bin/activate
python create_minio_bucket.py
```

Smoke test the backend manually:

```bash
cd /opt/magriplast/current/server
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another PuTTY window:

```bash
curl -i http://127.0.0.1:8000/health
curl -i http://127.0.0.1:8000/api/v1/docs
```

Stop the manual `uvicorn` with `Ctrl+C`.

## 8. Backend With PM2

Create PM2 config:

```bash
nano /opt/magriplast/current/ecosystem.config.cjs
```

Paste:

```js
module.exports = {
  apps: [
    {
      name: "magriplast-api",
      cwd: "/opt/magriplast/current/server",
      script: "/opt/magriplast/current/server/.venv/bin/uvicorn",
      args: "app.main:app --host 127.0.0.1 --port 8000 --workers 2",
      interpreter: "none",
      env: {
        PYTHONUNBUFFERED: "1"
      }
    },
    {
      name: "magriplast-worker-pdf",
      cwd: "/opt/magriplast/current/server",
      script: "/opt/magriplast/current/server/.venv/bin/celery",
      args: "-A app.core.celery_app.celery_app worker -Q pdf_processing -c 4 --loglevel=info --include=app.workers.pipeline",
      interpreter: "none",
      env: {
        PYTHONUNBUFFERED: "1"
      }
    },
    {
      name: "magriplast-worker-llm",
      cwd: "/opt/magriplast/current/server",
      script: "/opt/magriplast/current/server/.venv/bin/celery",
      args: "-A app.core.celery_app.celery_app worker -Q llm_tasks -c 4 --loglevel=info",
      interpreter: "none",
      env: {
        PYTHONUNBUFFERED: "1"
      }
    }
  ]
};
```

Start and persist:

```bash
cd /opt/magriplast/current
pm2 start ecosystem.config.cjs
pm2 list
pm2 logs magriplast-api --lines 80
pm2 logs magriplast-worker-pdf --lines 80
pm2 logs magriplast-worker-llm --lines 80
pm2 save
pm2 startup systemd -u root --hp /root
```

Run the command printed by `pm2 startup`, then:

```bash
pm2 save
systemctl status pm2-root --no-pager
curl -i http://127.0.0.1:8000/health
```

Useful PM2 commands:

```bash
pm2 list
pm2 monit
pm2 logs magriplast-api
pm2 restart magriplast-api
pm2 restart magriplast-worker-pdf
pm2 restart magriplast-worker-llm
pm2 stop magriplast-api
```

## 9. Frontend Build

Configure the frontend to call the same Nginx host under `/api/v1`:

```bash
cd /opt/magriplast/current/frontend
nano .env.production
```

Paste:

```env
VITE_API_URL=/api/v1
```

Install and build:

```bash
cd /opt/magriplast/current/frontend
npm ci
npm run build
ls -la dist
```

## 10. Nginx Frontend And API Proxy

Before adding the site, inspect current enabled sites again:

```bash
ls -la /etc/nginx/sites-enabled
nginx -T 2>/dev/null | grep -E 'server_name|listen|root|proxy_pass'
```

Create a new isolated Nginx site:

```bash
nano /etc/nginx/sites-available/magriplast
```

Paste:

```nginx
server {
    listen 80;
    server_name 5.199.136.2;

    root /opt/magriplast/current/frontend/dist;
    index index.html;

    client_max_body_size 60M;

    location /api/ {
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300;
        proxy_connect_timeout 60;
        proxy_send_timeout 300;
    }

    location /health {
        proxy_pass http://127.0.0.1:8000/health;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

Enable without deleting other sites:

```bash
ln -s /etc/nginx/sites-available/magriplast /etc/nginx/sites-enabled/magriplast
nginx -t
systemctl reload nginx
systemctl status nginx --no-pager
```

Test from the server:

```bash
curl -I http://127.0.0.1/
curl -i http://127.0.0.1/health
curl -i http://127.0.0.1/api/v1/docs
```

Test from your PC:

```text
http://5.199.136.2
http://5.199.136.2/health
http://5.199.136.2/api/v1/docs
```

## 11. Register First User

The app has public registration at `/api/v1/auth/register`.

From browser:

```text
http://5.199.136.2/register
```

Or by command:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","full_name":"Admin","password":"CHANGE_ADMIN_PASSWORD"}'
```

If you need to mark this user as superuser:

```bash
sudo -u postgres psql -d magriplast -c "UPDATE users SET is_superuser = true WHERE email = 'admin@example.com';"
```

## 12. Firewall

Inspect first:

```bash
ufw status verbose || true
iptables -S || true
```

Recommended public ports:

- Allow `22/tcp` for SSH.
- Allow `80/tcp` for the app.
- Do not publicly open `8000`, `9000`, `9001`, `5432`, or `6379`.

If UFW is active:

```bash
ufw allow OpenSSH
ufw allow 80/tcp
ufw deny 8000/tcp
ufw deny 9000/tcp
ufw deny 9001/tcp
ufw deny 5432/tcp
ufw deny 6379/tcp
ufw status verbose
```

## 13. Deployment Update Procedure

Before updating:

```bash
cd /opt/magriplast/current
git status
pm2 list
nginx -t
```

Pull and update backend:

```bash
cd /opt/magriplast/current
git pull
cd server
source .venv/bin/activate
pip install -r requirements.txt
pip install "python-jose[cryptography]" "passlib[bcrypt]"
alembic upgrade head
```

Update frontend:

```bash
cd /opt/magriplast/current/frontend
npm ci
npm run build
```

Restart app only:

```bash
pm2 restart magriplast-api
pm2 restart magriplast-worker-pdf
pm2 restart magriplast-worker-llm
pm2 list
systemctl reload nginx
```

Verify:

```bash
curl -i http://127.0.0.1:8000/health
curl -i http://127.0.0.1/health
pm2 logs magriplast-api --lines 50
```

## 14. Troubleshooting

Backend not responding:

```bash
pm2 list
pm2 logs magriplast-api --lines 100
ss -tulpn | grep 8000
curl -i http://127.0.0.1:8000/health
```

Workers not processing:

```bash
pm2 logs magriplast-worker-pdf --lines 100
pm2 logs magriplast-worker-llm --lines 100
redis-cli ping
redis-cli llen celery
```

Database issues:

```bash
systemctl status postgresql --no-pager
sudo -u postgres psql -d magriplast -c '\dt'
cd /opt/magriplast/current/server
source .venv/bin/activate
alembic current
alembic upgrade head
```

MinIO issues:

```bash
systemctl status magriplast-minio --no-pager
journalctl -u magriplast-minio -n 100 --no-pager
mc alias list
mc ls magriplast-local/magriplast-documents
```

Nginx issues:

```bash
nginx -t
systemctl status nginx --no-pager
journalctl -u nginx -n 100 --no-pager
tail -n 100 /var/log/nginx/error.log
```

Frontend calls wrong API:

```bash
cd /opt/magriplast/current/frontend
cat .env.production
npm run build
systemctl reload nginx
```

Expected value:

```env
VITE_API_URL=/api/v1
```

## 15. Final Checklist

- `curl http://127.0.0.1:8000/health` returns `{"status":"ok"}`.
- `pm2 list` shows `magriplast-api`, `magriplast-worker-pdf`, and `magriplast-worker-llm` online.
- `systemctl status magriplast-minio` is active.
- `mc ls magriplast-local/magriplast-documents` works.
- `sudo -u postgres psql -d magriplast -c '\dt'` shows tables.
- `nginx -t` passes.
- `http://5.199.136.2` loads the frontend.
- `http://5.199.136.2/api/v1/docs` loads FastAPI docs.
