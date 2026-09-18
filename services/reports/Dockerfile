FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY packages ./packages
ENV PYTHONPATH=/app/packages
COPY services/reports/app ./services/reports/app
EXPOSE 8005
CMD ["uvicorn", "services.reports.app.main:app", "--host", "0.0.0.0", "--port", "8005"]
