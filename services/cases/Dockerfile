FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY packages ./packages
ENV PYTHONPATH=/app/packages
COPY services/cases/app ./services/cases/app
EXPOSE 8002
CMD ["uvicorn", "services.cases.app.main:app", "--host", "0.0.0.0", "--port", "8002"]
