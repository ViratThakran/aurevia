# Voice worker image (development).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

RUN pip install --no-cache-dir uv==0.11.7 \
    && useradd --create-home --uid 10001 app

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev && chown -R app:app /app

USER app
# Model files (voice activity detection) are fetched at build time, not on the first call.
RUN AUREVIA_BACKEND_URL=http://unused python -m aurevia_voice.main download-files

CMD ["python", "-m", "aurevia_voice.main", "start"]
