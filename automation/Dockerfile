FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY config ./config
RUN mkdir -p /app/data

CMD ["python", "-m", "soloist_agent", "run"]
