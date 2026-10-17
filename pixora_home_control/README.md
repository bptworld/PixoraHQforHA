# Pixora Home Control

Connects Home Assistant to Planner, Home Control, and Flows using a secure outbound connection. No public Home Assistant address, Nabu Casa subscription, long-lived token, or port forwarding is needed.

1. Add `https://github.com/bptworld/PixoraHQforHA` to your Home Assistant app/add-on repositories.
2. Install **Pixora Home Control**.
3. In **Planner → Smart Home → Home Assistant**, choose **Pair Home Control app**.
4. Copy the pairing code into this app’s **Configuration → pairing_code**, save, and start the app. Codes expire after ten minutes and work once.
5. Enable **Start on boot** and **Watchdog**. Planner will show the app as online.

The app uses Home Assistant’s internal API permission, receives local state events, and executes commands through the standard local service API. The Flow engine remains on Pixora’s server. Internet access is required; old commands are not queued for later execution. Uncertain command results are never retried automatically.

Disconnecting Home Assistant in Planner revokes this app’s credential. To reconnect, generate a new pairing code, replace `pairing_code`, and restart the app. Previously chosen device tiles and Flows remain in Pixora.

Requires Home Assistant OS with the app/add-on store. A standalone Container installation is not supported by this package.

## Local installation before release

Extract the supplied ZIP so its `pixora_home_control` folder is at `/addons/pixora_home_control` on Home Assistant. Reload the app/add-on store, then install **Pixora Home Control** from **Local apps**. Leave the app stopped until the matching Pixora server release is deployed; pairing is not available on the previous server release. Then follow steps 3–5 above.

## Server deployment

The Pixora connector socket and existing Flow engine run in the same server process. Deploy one Render instance with `WEB_CONCURRENCY=1` (set in this release’s Render blueprint). Multiple workers or replicas require a shared connection broker before enabling this transport. Pairing credentials use the existing encrypted Home Assistant connection storage. No credentials are placed in URLs or logs.
