FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# API dependencies
COPY apps/api/requirements.txt ./requirements.txt

RUN pip install --no-cache-dir -r requirements.txt

# Copy API
COPY apps/api/ ./

# Copy the public widget from the repository
COPY packages/widget/widget.js /app/packages/widget/widget.js

# Non-root runtime user
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app

USER appuser

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]