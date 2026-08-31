# syntax=docker/dockerfile:1

# Multi-arch base image -- works on the Pi 4's arm64 as well as amd64 dev
# machines. Slim variant keeps the image small on a 32GB SD card.
FROM python:3.12-slim

WORKDIR /app

# System deps needed to build a couple of Python wheels (e.g. some web3/
# cryptography transitive deps) on arm64, where prebuilt wheels aren't
# always available.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libssl-dev \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Secrets and state are bind-mounted at runtime (see docker-compose.yml) --
# nothing sensitive gets baked into the image.

# Run as a non-root user inside the container.
RUN useradd --create-home --uid 1000 monitor \
    && chown -R monitor:monitor /app
USER monitor

CMD ["python", "main.py"]
