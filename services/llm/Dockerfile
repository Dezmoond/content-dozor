FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY packages ./packages
ENV PYTHONPATH=/app/packages:/diplom/llama_classific/llama_train
COPY services/llm/app ./services/llm/app
EXPOSE 8004
CMD ["uvicorn", "services.llm.app.main:app", "--host", "0.0.0.0", "--port", "8004"]
