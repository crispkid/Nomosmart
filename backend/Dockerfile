# syntax=docker/dockerfile:1.7

FROM ubuntu:24.04@sha256:69cecf4bbf72d2d44a9eef1b71fb98c7fb973d78af11399deccef19beb008ad9 AS builder
WORKDIR /app

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    ca-certificates \
    python3 \
    python3-venv \
  && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
COPY app ./app
COPY main.py migrate.py models.py connection.py ./
RUN python3 -m venv /opt/uv \
  && printf '%s\n' 'uv==0.11.33 --hash=sha256:36a98c68ba5c3bb59469414f54aaf00bd3134a647ca34509bc53d133ed8e0b5d --hash=sha256:71d00a28beb3924c593ba7ec248263679ae1f7c0f63a8cccc75e7d11ccb2adce --hash=sha256:9542178978b0b6f16a7ae99e55aca039f493a1edb373a15d7993eab80a28615a' \
    | /opt/uv/bin/pip install --no-cache-dir --require-hashes -r /dev/stdin \
  && UV_PROJECT_ENVIRONMENT=/opt/venv /opt/uv/bin/uv sync --frozen --no-dev --no-editable

FROM ubuntu:24.04@sha256:69cecf4bbf72d2d44a9eef1b71fb98c7fb973d78af11399deccef19beb008ad9 AS runner
WORKDIR /app

ARG PANDOC_VERSION=3.1.3+ds-2
ARG TESSERACT_VERSION=5.3.4-1build5
ARG TESSDATA_VERSION=1:4.1.0-2

ENV DEBIAN_FRONTEND=noninteractive
ENV HOME="/home/nomosmart"
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    bubblewrap \
    ca-certificates \
    curl \
    libpq5 \
    pandoc=${PANDOC_VERSION} \
    poppler-utils \
    python3 \
    tesseract-ocr=${TESSERACT_VERSION} \
    tesseract-ocr-chi-tra=${TESSDATA_VERSION} \
    tesseract-ocr-eng=${TESSDATA_VERSION} \
  && rm -rf /var/lib/apt/lists/* \
  && groupadd --gid 10001 nomosmart \
  && useradd --uid 10001 --gid nomosmart --home-dir /home/nomosmart --create-home --shell /usr/sbin/nologin nomosmart

COPY --from=builder /opt/venv /opt/venv
COPY --chown=nomosmart:nomosmart app ./app
COPY --chown=nomosmart:nomosmart main.py migrate.py models.py connection.py ./

USER nomosmart
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
