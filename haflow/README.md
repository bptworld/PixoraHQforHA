# HAFlow

**Moving from the old HAFlow? Import your saved flows in this app.**

1. Open the **old HAFlow** app, save changes, expand **Library**, and choose **Export Backup**. Keep the downloaded JSON file.
2. In **Settings → Apps → the old HAFlow**, turn off **Start on boot** and **Watchdog**, then **Stop** it. Keep it installed until the transfer is verified.
3. Add `https://github.com/bptworld/PixoraHQforHA` under **App store → ⋮ → Repositories**. Install **HAFlow from PixoraHQ for Home Assistant**, version **0.1.68 or later**, then start and open it.
4. Click the bold transfer notice's **Import old HAFlow** button in the new app. Choose your exported JSON file. Single **Export Flow** files also work.
5. Close the import window, select each imported flow, and check its devices and connections. **Imported flows start paused; existing flows are preserved.**
6. With the old app stopped, click **Resume** for the reviewed flows and test their triggers. Enable **Start on boot** and **Watchdog** for the new app after checking it works.

**Do not run both copies of the same automations.** Keep the old app stopped and retain your export. Settings, logs, history and pending timers do not transfer. Device references are retained; check them if you moved to another Home Assistant. Import the file once: importing again creates additional copies.

**Need to go back?** Stop the new app first, then start the old one. The old app's saved flows are unchanged. Never uninstall the old app until you have verified the new one.


A Home Assistant app for HAFlow, a flow-based automation editor and runner.

## Installation

To install this app, follow these steps:

1. Navigate to the app store in the Home Assistant UI: **Settings**, **Apps**, then **Install App**.
2. Select the three vertical dots in the upper right-hand corner and select **Repositories**.
3. On the bottom of the **Repositories** screen, click **Add**,
4. Enter this project's GitHub page URL and click **Add**:
   ```text
   https://github.com/bptworld/PixoraHQforHA
   ```

5. After adding the repository, go back to the **App Store**, select the three vertical dots in the upper right-hand corner, and select **Check for updates**.
6. Scroll down the **App Store** or use search to find **HAFlow**.
7. Select **HAFlow** and click **Install**.
8. Start HAFlow and open it from the app page or sidebar.

## Move from the old HAFlow repository

Follow the [step-by-step Flow transfer guide](TRANSFER_FLOWS.md) to export from the old app, install this version, import paused copies, check devices, and switch over safely. It also covers single-flow files, duplicate imports and going back to the old app.

## App

The HAFlow app source is in [`haflow/`](haflow/).

HAFlow runs inside Home Assistant and connects to Home Assistant Core automatically through the Supervisor API. No long-lived access token is required.
NOTE: This does not need HACS, this is a HA App!

## Features

See the [detailed feature list](haflow/FEATURES.md) for the full HAFlow capability overview.

## Examples

Example importable flows are available in [`haflow/examples/`](haflow/examples/):

- `simple-motion-light.json`
- `5-button-pico-example.json`

---

Brought to you by [PixoraHQ.com](https://pixorahq.com/).

## Built-in Insight activity

HAFlow reports each device action’s Flow/trigger origin to Insight using the HA command context. Diagnostics are bounded and never replay commands. This is automatic when using the matching app updates; no extra
companion installation or training step is needed. Insight remains optional and
local. Missing reports leave the cause unknown; commands are never repeated to
fill a log. Older records without provenance are not reconstructed.
