FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY packages ./packages
ENV PYTHONPATH=/app/packages:/diplom/llama_classific/llama_train
COPY services/worker/app ./services/worker/app
CMD ["celery", "-A", "services.worker.app.tasks:celery_app", "worker", "--loglevel=info", "-Q", "celery"]
