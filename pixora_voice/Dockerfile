ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM ${BUILD_FROM}
RUN apk add --no-cache python3 py3-aiohttp
COPY app.py diagnostics.py planner_phrases.py index.html icon.svg run.sh /app/
COPY custom_components /app/custom_components
RUN chmod 0755 /app/run.sh
CMD ["/app/run.sh"]
