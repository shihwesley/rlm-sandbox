FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY sandbox/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY sandbox/ sandbox/

EXPOSE 8080

CMD ["uvicorn", "sandbox.server:app", "--host", "0.0.0.0", "--port", "8080"]
