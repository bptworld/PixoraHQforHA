ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM ${BUILD_FROM}

ARG BUILD_VERSION=1.5.0

LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app"

ENV PYTHONUNBUFFERED=1

RUN apk upgrade --no-cache \
    && apk add --no-cache python3

COPY app.py /app/app.py
COPY run.sh /run.sh
RUN chmod 0755 /run.sh

CMD [ "/run.sh" ]
