ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM ${BUILD_FROM}
RUN apk add --no-cache python3 py3-aiohttp tzdata
COPY app.py collector.py model.py store.py index.html ui.js style.css icon.svg run.sh /app/
RUN chmod 0755 /app/run.sh
CMD ["/app/run.sh"]
