FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps needed by pypdf/python-docx on slim images are minimal; nothing
# extra required at runtime.

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Bundle the public widget script. The source lives at <repo>/packages/widget
# (outside this build context); it is provided as the extra 'widget' build
# context by docker-compose.prod.yml so it is never duplicated.
COPY --from=widget /widget.js /app/packages/widget/widget.js

# Non-root runtime user for defense-in-depth.
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]