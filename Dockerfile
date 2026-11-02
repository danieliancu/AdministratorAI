FROM python:3.13-slim

ARG REQUIREMENTS=requirements.txt

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r "${REQUIREMENTS}"

COPY . .

RUN useradd --create-home --uid 1000 app
USER app

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2"]
