FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Run as a non-root user
RUN useradd --create-home --uid 10001 appuser

# Install dependencies first so this layer is cached until requirements change
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY main.py .

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/todos')"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
