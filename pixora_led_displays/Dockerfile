ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM ${BUILD_FROM}
ENV PYTHONUNBUFFERED=1
RUN apk add --no-cache python3 py3-aiohttp py3-pillow tzdata py3-pip py3-virtualenv py3-cryptography py3-cffi py3-yaml
RUN python3 -m venv --system-site-packages /opt/installer && /opt/installer/bin/pip install --no-cache-dir bitstring==3.1.9 esptool==5.1.0 esp-idf-nvs-partition-gen==0.3.0
ENV PATH="/opt/installer/bin:$PATH"
COPY display_setup.py display_setup.html display_usb.js ESPTOOL-JS-LICENSE.txt first-install.bin firmware_updates.py automation.py insight_origin.py app.py index.html studio.py studio.html card_store.py card_updates.py custom_cards.py custom_card_starter.py Pixora-Codex-Card-Brief.md card_worker.py graphic_cache.py graphic_layout.py quiet_hours.py standings.py pipeline.py special_graphics.py card_catalog.json /app/
COPY custom_components /app/custom_components
COPY run.sh /run.sh
RUN chmod 0755 /run.sh
CMD ["/run.sh"]
