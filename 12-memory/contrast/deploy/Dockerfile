FROM ghcr.io/astral-sh/uv:0.13.7-python3.12-trixie-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY 12-memory/contrast/ ./12-memory/contrast/

EXPOSE 80
CMD ["python", "12-memory/contrast/web.py", "--host", "0.0.0.0", "--port", "80"]
