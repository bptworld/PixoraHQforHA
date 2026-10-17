ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM ${BUILD_FROM}
ENV PYTHONUNBUFFERED=1
RUN apk add --no-cache python3 py3-aiohttp py3-pillow
COPY automation.py app.py index.html /app/
COPY custom_components /app/custom_components
CMD ["python3", "/app/app.py"]
