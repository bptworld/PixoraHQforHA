# 1.1.0

- Redesign the local app around a 142-card catalog, editable saved decks, per-display playback and previews.
- Download and verify only cards used by saved decks. Remove unused card-specific files; keep shared helpers, fonts and common assets on the hub.
- Add device groups, brightness, quiet hours, local uploads and a simple Graphics Lab.
- Add native HA Play/Pause deck actions and automatic companion registration. HA messages interrupt decks and playback resumes afterwards.
- Use local S3 firmware 2.0.19 for deck priority, brightness and reboot controls. Firmware source stays private.

# 1.0.8

- Reconnect automatically after a one-click firmware update to restore saved pairing and the Waiting screen.
- Confirm the running version after restart and refresh the installed-version text. Show an unverified outcome clearly without resending firmware.

# 1.0.7

- Load Home Assistant’s container environment before starting the app, restoring Supervisor discovery and the HA restart button.
- Hide the restart button when HA API access is unavailable and show an actionable error.

# 1.0.6

- Check published S3 firmware and offer one-click download, verification and local installation.
- Show installed/latest versions and preview labels; preserve manual file installation under advanced controls.

# 1.0.5

- Install companion updates automatically at app startup.
- Register connected displays with HA automatically using saved pairing details; update existing connections without duplicate entities.
- Replace manual setup steps with clear status and a single explicit HA restart button when needed.

# 1.0.4

- Audit pairing, reconnecting, card acknowledgements, HA reconfiguration and safe companion installation.
- Keep action feedback beside its button and refresh local setup instructions.

# 1.0.3

- Add Rename and Remove controls for saved displays, with removal confirmation and durable changes.

- Show connection progress and a clear success/error message beside Connect display. Clear the name and IP only after success; keep them on failure and select the connected display for sending.

- Remove the unnecessary Important notice and migration wording from this new app’s Information page.

# 1.0.2

**IMPORTANT — This is the current app from PixoraHQ for Home Assistant.**

**App repository: `https://github.com/bptworld/PixoraHQforHA`**

Add this repository once in **Settings → Apps → App store → ⋮ → Repositories** to find all PixoraHQ Home Assistant apps and their updates.

**LED Displays runs locally on your HA hub and sends directly over Wi-Fi to S3 64x32 and 128x32 panels. No Cloud account is needed.** This app update does not install panel firmware automatically.

Brought to you by [PixoraHQ.com](https://pixorahq.com/).

- Publish an app update so existing installations receive the bold Information-page notice and setup instructions. No automatic migration or device actions.

# Changelog

## 1.0.1

- Add the PixoraHQ.com credit to app information and documentation and the app interface.

