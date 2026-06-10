module.exports = {
  apps: [
    {
      name: "magriplast-api",
      cwd: "/opt/magriplast/current/server",
      script: "/opt/magriplast/current/server/.venv/bin/uvicorn",
      args: "app.main:app --host 127.0.0.1 --port 8002 --workers 2",
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
