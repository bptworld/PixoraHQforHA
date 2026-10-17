**IMPORTANT — This is the current app from PixoraHQ for Home Assistant.**

**App repository: `https://github.com/bptworld/PixoraHQforHA`**

Add this repository once in **Settings → Apps → App store → ⋮ → Repositories** to find all PixoraHQ Home Assistant apps and their updates.

**Moving from an older repository?** Back up the old app, turn off its **Start on boot** and **Watchdog**, and **Stop** it before starting this replacement. Keep the old installation until this one works. Follow the pairing steps below; app configuration and credentials do not transfer automatically. Keep only the replacement running.

Your Pixora account is at **[planner.pixorahq.com](https://planner.pixorahq.com/)**. **The Locator phone app is required**; create the Home Assistant pairing token in the phone app under **Settings → Home Assistant App**.

Brought to you by [PixoraHQ.com](https://pixorahq.com/).

---

# Pixora Locator Home Assistant App

Pixora Locator privately connects actively sharing phones to Home Assistant using a pairing token.

Access your Pixora account at [planner.pixorahq.com](https://planner.pixorahq.com/). The Locator phone app is required; create the Home Assistant pairing token in that phone app using the steps below.

## Install

1. Navigate to the app store in the Home Assistant UI: **Settings**, **Apps**, then **Install App**.
2. Select the three vertical dots in the upper-right corner and select **Repositories**.
3. At the bottom of the **Repositories** screen, click **Add**.
4. Enter `https://github.com/bptworld/PixoraHQforHA` and click **Add**.
5. Go back to the **App Store**, select the three vertical dots, and select **Check for updates**.
6. Scroll down the **App Store** or use search to find **Pixora Locator**.
7. Select **Pixora Locator** and click **Install**.
8. In the Pixora Locator phone app, open **Settings → Home Assistant App** and create a pairing token.
9. Before starting the Home Assistant App, open its **Configuration** tab, paste the token, and click **Save**.
10. Start Pixora Locator and open it from the app page or sidebar.

The App starts automatically with Home Assistant. Normal synchronization reads only the current location point for each actively sharing phone. Creating a migration file reads selected Home Assistant zones only; recorder history is never accessed.

## Import Home Assistant Places

1. Open the Pixora Locator App page in Home Assistant and select **Migrate Home Assistant zones**.
2. Choose up to 50 zones and create the checksummed `.pixora` file.
3. On the phone, open **Locator → Settings → Home Assistant App → Import Home Assistant Places**.
4. Choose the file, review the zones, turn off any you do not want, and select **Import Places**.
5. After Locator confirms the import, delete the downloaded file.

A Locator household can keep up to 75 Places. New Places start fresh, just like Places added directly in Locator; an existing matching Place keeps its current activity and settings. The import is a one-time copy, not a continuing synchronization.

The file contains only the selected zone definitions. It contains no tracker records or location, arrival, or departure history, and never contains Home Assistant passwords, access tokens, automations, or unrelated sensor data.

The Pixora Locator Home Assistant App can run beside the official Home Assistant Companion App while you create the file. It reads the zone definitions through Home Assistant and does not change, disable, or replace the Companion App.

Each phone has a normal `device_tracker` for maps and zones. The same device also shows separate Place, Latitude, Longitude, GPS Accuracy, Since, Movement, Sharing Mode, Last Report, Battery, Charging, Speed, Distance from Home, Location Health, and Battery Unrestricted sensor rows, making the details directly usable in dashboards and automations. Home Assistant shows new App versions under **Settings → Apps** after its repository update check runs; use **Check for updates** in the App Store menu to check immediately.

Distance from Home uses the center of Home Assistant's **Home** zone, not a driving route or a saved Place boundary. Set `distance_units` to `mi` (miles/mph, default) or `km` (kilometers/km/h) in the App configuration. Location Health shows Current, Delayed, Stale, One Time, or Off from PixoraHQ's current feed. Battery Unrestricted indicates Android's battery-optimization exemption, not every manufacturer's background restriction; unsupported or older phone apps show unavailable. Measurements come from existing location deliveries, with no extra GPS polling.

---

Brought to you by [PixoraHQ.com](https://pixorahq.com/).
