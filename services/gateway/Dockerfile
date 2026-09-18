FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY packages ./packages
ENV PYTHONPATH=/app/packages
COPY services/gateway/app ./services/gateway/app
COPY services/worker/app ./services/worker/app
EXPOSE 8000
CMD ["uvicorn", "services.gateway.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
