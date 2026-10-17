# Pixora LED Displays

A separate Home Assistant app for sending cards directly to Pixora LED panels
over your local Wi-Fi. No Pixora account, Cloud service, MQTT broker or internet
connection is needed for sending cards.

## Set up

1. Install this app in Home Assistant, start it, and choose **Open Web UI**.
2. Update your panel to **2.0.14 local-display user-OTA firmware** matching its
   hardware (MatrixPortal S3 64x32 or 128x32). User-OTA preserves Wi-Fi and panel
   settings. Do not use a factory/reset firmware image for this update.
3. Restart the panel. Within two minutes, enter its IP address in **Add a
   display**. Give it a friendly name and select **Connect display**.
4. Type a message and select **Show card**, or choose your own image.

Home Assistant and the panel must be on the same IPv4 subnet. Reserve the panel's
address in your router. To update a saved address, reconnect the same panel with
its new address. A panel restart reopens pairing, retaining the existing key so
other authorized clients continue working. Pairing lasts two minutes; ordinary
card sending continues after it closes.

The text card uses the panel's compact font (plain ASCII, up to 160 characters).
Short messages work best; long messages can extend beyond the panel. Use a PNG,
JPEG or WebP image for precise layouts, other fonts, icons or non-ASCII text.
Images fit the panel with black borders and no cropping; animated files use the
first frame. Cards display for 1–300 seconds. A new accepted card replaces the
currently displayed local card. A second pending request receives a busy error.

This is a local-only firmware and HA app. Cards clear after their duration. It
has no online playback, online account setup, server polling or internet
requirement. Firmware updates after installation are sent from this app's
**Update panel firmware** section directly over the LAN.

## Automations

Open **Use in HA automations** in this app and choose **Install automation
actions**. This installs only the `pixora_local` custom integration into
`/homeassistant/custom_components` and backs up any previous copy under app data.
Restart Home Assistant, then add **Pixora LED (Local)** under Settings → Devices
& services. Restart each panel before connecting it by IP address.

Each paired panel becomes a native HA `notify` entity. In an automation choose
**Send a notification message** (`notify.send_message`) and select your panel.
This sends a white message card for 10 seconds. For more control choose
**Pixora LED (Local): Show card** or **Show image card**.
Select your display and content. No YAML is required. Image actions accept local
files in Home Assistant's allowed paths, such as `/config/www/washer.png`.

The companion integration sends directly to the panel; automations do not depend
on the app page being open. Panel authorization survives both app and HA restarts.
There is no automatic retry when a delivery outcome is uncertain.

## App repository

Add https://github.com/bptworld/PixoraHQforHA to Home Assistant's app repositories.
Install **Pixora LED Displays** from the PixoraHQ for Home Assistant section.
This is an initial local release: firmware compilation and software checks pass;
physical-panel and Supervisor installation verification are still pending.

The firmware binary is released separately. Its private source is not included
in this public app repository. Existing Cloud firmware needs a one-time upload
using its current updater or USB; later updates use this local app directly.

## Local access

The app UI uses Home Assistant Ingress and accepts requests only from Supervisor;
it exposes no host port. Pairing creates a panel-specific key stored in HA/app
data and the panel's preferences, never in browser state. The panel rejects
off-subnet and browser-origin requests. LAN HTTP is used; keep panels on your
trusted local network. No commands or keys are sent to Pixora Cloud.

Only MatrixPortal S3 64x32 and 128x32 are supported by this release. Both use
one S3 user-OTA image; the existing saved panel target selects the width.

---

Brought to you by [PixoraHQ.com](https://pixorahq.com/).
