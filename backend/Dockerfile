# syntax=docker/dockerfile:1.7

FROM ubuntu:24.04@sha256:69cecf4bbf72d2d44a9eef1b71fb98c7fb973d78af11399deccef19beb008ad9 AS builder
WORKDIR /app

ARG OPENSSL_VERSION=3.0.13-0ubuntu3.16
ARG APT_VERSION=2.8.4ubuntu0.1

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get -o Acquire::Retries=0 update \
  && apt-get -o Acquire::Retries=0 install -y --no-install-recommends \
    apt=${APT_VERSION} \
    libapt-pkg6.0t64=${APT_VERSION} \
    ca-certificates \
    openssl=${OPENSSL_VERSION} \
    libssl3t64=${OPENSSL_VERSION} \
    python3 \
    python3-venv \
  && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
COPY vendor/anyio/4.14.2+nomosmart.2 ./vendor/anyio/4.14.2+nomosmart.2
COPY vendor/python-multipart/0.0.32+nomosmart.1 ./vendor/python-multipart/0.0.32+nomosmart.1
COPY app ./app
COPY main.py migrate.py models.py ./
RUN python3 -m venv /opt/uv \
  && printf '%s\n' 'uv==0.13.4 --hash=sha256:e90ab42825587821096cb0d071e387468da38cfa22818c91f9c0b3c0453048e8 --hash=sha256:05e4332791b4d55b6dde8695b7fa6079b26991519f44760887c5dfbd5ca4fe53 --hash=sha256:7b3cdf868e5415631fe797b648c0d6945d38d388f23367bdd0b6332e80a1fcb0' \
    | /opt/uv/bin/pip install --no-cache-dir --require-hashes -r /dev/stdin \
  && UV_PROJECT_ENVIRONMENT=/opt/venv /opt/uv/bin/uv sync --frozen --no-dev --no-editable

FROM ubuntu:24.04@sha256:69cecf4bbf72d2d44a9eef1b71fb98c7fb973d78af11399deccef19beb008ad9 AS runner
WORKDIR /app

ARG OPENSSL_VERSION=3.0.13-0ubuntu3.16
ARG APT_VERSION=2.8.4ubuntu0.1
ARG BROTLI_VERSION=1.1.0-2ubuntu0.1
ARG PCRE2_VERSION=10.42-4ubuntu2.2
ARG PERL_VERSION=5.38.2-3.2ubuntu0.7
ARG ZLIB_VERSION=1:1.3.dfsg-3.1ubuntu2.3

ENV DEBIAN_FRONTEND=noninteractive
ENV HOME="/home/nomosmart"
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get -o Acquire::Retries=0 update \
  && apt-get -o Acquire::Retries=0 install -y --no-install-recommends \
    apt=${APT_VERSION} \
    libapt-pkg6.0t64=${APT_VERSION} \
    ca-certificates \
    curl \
    openssl=${OPENSSL_VERSION} \
    libssl3t64=${OPENSSL_VERSION} \
    libpq5 \
    libbrotli1=${BROTLI_VERSION} \
    libpcre2-8-0=${PCRE2_VERSION} \
    perl-base=${PERL_VERSION} \
    zlib1g=${ZLIB_VERSION} \
    python3 \
  && rm -rf /var/lib/apt/lists/* \
  && groupadd --gid 10001 nomosmart \
  && useradd --uid 10001 --gid nomosmart --home-dir /home/nomosmart --create-home --shell /usr/sbin/nologin nomosmart

COPY --from=builder /opt/venv /opt/venv
COPY --chown=nomosmart:nomosmart app ./app
# PDF recognition uses the configured native document model; no local OCR tools.
COPY --chown=nomosmart:nomosmart main.py migrate.py models.py ./
COPY --chown=nomosmart:nomosmart scripts/soft_deleted_residue_cleanup.py ./scripts/soft_deleted_residue_cleanup.py

USER nomosmart
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
