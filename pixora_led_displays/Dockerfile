ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM ${BUILD_FROM}
ENV PYTHONUNBUFFERED=1
RUN apk add --no-cache python3 py3-aiohttp py3-pillow tzdata
COPY firmware_updates.py automation.py app.py index.html studio.py studio.html card_store.py card_worker.py pipeline.py special_graphics.py card_catalog.json /app/
COPY custom_components /app/custom_components
COPY run.sh /run.sh
RUN chmod 0755 /run.sh
CMD ["/run.sh"]
