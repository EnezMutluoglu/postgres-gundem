# syntax=docker/dockerfile:1
FROM debian:bookworm-slim AS build
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates cmake ninja-build g++ && rm -rf /var/lib/apt/lists/*
COPY release/build-engine.sh /build-engine.sh
RUN curl -fsSL --retry 4 https://codeload.github.com/ggml-org/llama.cpp/tar.gz/refs/tags/b12532 -o /tmp/src.tgz && bash /build-engine.sh "$TARGETARCH" /tmp/src.tgz /out && mkdir /engine && tar -xf /out/*.tar.gz --strip-components=1 -C /engine
FROM docker:29-cli AS cli
FROM python:3.11-slim-bookworm
LABEL org.opencontainers.image.source="https://github.com/EnezMutluoglu/postgres-gundem"
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates openssl libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --from=build /engine /engine
COPY --from=cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=cli /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose
COPY app.py feeds.py community.py translation_jobs.py news_search.py admin.py archive.py turkish.json VERSION LICENSE ./
COPY static ./static
COPY templates ./templates
COPY container ./container
COPY deploy/container ./deploy/container
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 GUNDEM_CONTAINER=1 GUNDEM_BIND=0.0.0.0 GUNDEM_DATA=/data GUNDEM_MODEL_URL=http://model:18081 GUNDEM_MODEL_TIMEOUT=3600
USER 10001:10001
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD ["python","/app/container/probe.py","web"]
CMD ["python","app.py"]

