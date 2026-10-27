FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# constraints.txt pins every transitive version so a rebuild never pulls a
# release published the same day (supply-chain cooldown). Regenerate with:
#   uv pip compile requirements.txt --exclude-newer <today-14d> --python-version 3.13 \
#     --python-platform x86_64-manylinux_2_28 --no-header --annotation-style line -o constraints.txt
COPY requirements.txt constraints.txt /app/
RUN pip install --no-cache-dir -r /app/requirements.txt -c /app/constraints.txt

COPY app /app/app

# Alembic config, migrations and one-off scripts ship with the image so schema
# changes can be applied from a Cloud Run Job (the Cloud SQL instance is not
# reachable from the office network).
COPY alembic.ini /app/alembic.ini
COPY migrations /app/migrations
COPY scripts /app/scripts

# Cloud Run listens on $PORT (default 8080)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
