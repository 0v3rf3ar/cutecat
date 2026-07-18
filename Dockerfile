#   docker build -t cutecat .
#   docker run -it --rm \
#       -v cutecat-config:/root/.cutecat \
#       -v "$PWD/workspace:/workspace" \
#       cutecat

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        curl \
        ca-certificates \
        chromium \
        fonts-liberation \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/cutecat
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir '.[discord,voice]'

ENV HF_HOME=/root/.cutecat/models

VOLUME ["/root/.cutecat", "/workspace"]
WORKDIR /workspace

ENTRYPOINT ["cutecat"]
