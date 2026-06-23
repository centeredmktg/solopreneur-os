FROM python:3.12-slim

WORKDIR /app

# Install deps first for layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Explicit COPY allowlist — add new top-level dirs here before deploying.
COPY app/ ./app/
COPY static/ ./static/

ENV PORT=8000
EXPOSE 8000

# Railway provides $PORT at runtime.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
