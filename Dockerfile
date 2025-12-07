# syntax=docker/dockerfile:1

FROM python:3.12-slim
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONPATH="/app/src:$PYTHONPATH"
ENV XDG_CACHE_HOME=/app/cache
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY ./.venv /opt/venv
COPY src ./src
ENTRYPOINT ["python", "src/tool_bot/main.py"]
