# Python 3.13 to match the version CI runs the suite on, so the image executes what the
# tests actually validated. pyproject allows >=3.11.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FTA_OUTPUT_DIR=/data/out

WORKDIR /app

# README.md is required because pyproject declares readme = "README.md"; omitting it
# fails the build rather than merely losing metadata.
COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir ".[server]"

# /data is the volume mount point. Ownership is set before dropping privileges so the
# report writer can create out/<slug>/ at runtime.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data/out \
    && chown -R app:app /data
USER app

EXPOSE 8000

# Exactly one worker, deliberately. RunRegistry holds run state in process memory, so a
# second worker would own a second registry and any run created through one would return
# 404 from the other. Scaling this service means fixing that first.
CMD ["sh", "-c", "exec uvicorn founding_team_analyzer.server:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
