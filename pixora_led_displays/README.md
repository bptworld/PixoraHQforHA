# Pixora LED Studio

<p>
  <a href="https://raw.githubusercontent.com/bptworld/PixoraHQforHA/main/docs/images/led-panel-clock-lifestyle.png"><img src="https://raw.githubusercontent.com/bptworld/PixoraHQforHA/main/docs/images/led-panel-clock-lifestyle.png" alt="AI lifestyle illustration of a clock and weather LED display on a cabinet" width="300"></a>
  <a href="https://raw.githubusercontent.com/bptworld/PixoraHQforHA/main/docs/images/led-panel-sports-lifestyle.png"><img src="https://raw.githubusercontent.com/bptworld/PixoraHQforHA/main/docs/images/led-panel-sports-lifestyle.png" alt="AI lifestyle illustration of a sports LED display on a desk" width="300"></a>
  <a href="https://raw.githubusercontent.com/bptworld/PixoraHQforHA/main/docs/images/led-studio-decks.png"><img src="https://raw.githubusercontent.com/bptworld/PixoraHQforHA/main/docs/images/led-studio-decks.png" alt="Pixora LED Studio decks and display controls in Home Assistant" width="300"></a>
</p>

*LED display lifestyle illustrations (AI-generated) and an LED Studio screenshot — click any image to enlarge.*

Build decks on your Home Assistant hub and serve them straight to MatrixPortal S3 **64×32** and **128×32** displays over local Wi-Fi. No Pixora Cloud account or rendering server is used.

Brought to you by [PixoraHQ.com](https://pixorahq.com/).

## Build your own display

**No soldering needed with the example Adafruit parts below.** Assembly is simply plugging in the panel connections and a couple of cables, including USB-C for power. For a 128×32 display, connect the second panel with the ribbon and power cables.

The products linked below are examples of parts you can buy, not a required shopping list or an endorsement. PixoraHQ is not affiliated with, sponsored by, or endorsed by Adafruit. Product names and trademarks belong to their respective owners. Purchases, warranties, returns and hardware support are handled by the seller. Check compatibility before choosing alternatives; Pixora firmware currently supports MatrixPortal S3 controllers with 64×32 or 128×32 displays.

| Part | 64×32 display | 128×32 display |
| --- | --- | --- |
| [Adafruit Matrix Portal S3 — product 5778](https://www.adafruit.com/product/5778) | 1 controller | 1 controller |
| [64×32 RGB LED Matrix, 4 mm pitch — product 2278](https://www.adafruit.com/product/2278) | 1 panel | 2 panels, side by side |
| USB-C **data** cable for flashing and power | 1 | 1 |
| USB power supply suitable for the display | 1 | 1, sized for both panels |
| HUB75/IDC ribbon and panel power cables | Included with the Adafruit panel | Included with the Adafruit panels |
| Mounting hardware or enclosure | As needed | As needed for both panels |

The display is powered through the Matrix Portal S3's USB-C connection. The Adafruit panels include the required ribbon and panel power cables; panels from other sellers may not, so check what is included before ordering extras. The controller and panels are separate purchases; a USB-C power supply is not included with the controller.

For 128×32, connect the first panel's **OUT** to the second panel's **IN**, power both panels, and select **128×32** during Wi-Fi setup. Both sizes use the same controller and Pixora firmware. Follow [Adafruit's MatrixPortal S3 assembly guide](https://learn.adafruit.com/adafruit-matrixportal-s3) for connector orientation and power wiring. Adafruit specifies up to **4 A at 5 V per panel**; size the power supply and wiring for the number of panels. See the [panel power requirements](https://www.adafruit.com/product/2278) before choosing a supply.

You also need a running Home Assistant installation with app support and a **2.4 GHz Wi-Fi network** for the displays.

## First USB installation and Wi-Fi setup

For a new MatrixPortal S3 controller, download the **[USB first-install firmware 2.0.27](https://github.com/bptworld/PixoraHQforHA/raw/refs/heads/main/firmware/usb/2.0.27/pixora-v2.0.27-s3-first-install-usb.bin)**. One file supports **64×32 and 128×32**.

Follow the **[USB flashing and Wi-Fi setup instructions](https://github.com/bptworld/PixoraHQforHA/blob/main/firmware/usb/2.0.27/README.md)**. Flash the complete image at **0x0**, join the panel's `Pixora-…` network using its displayed password, then open **http://192.168.4.1** to enter your **2.4 GHz** home Wi-Fi and select the panel size. Reconnect to home Wi-Fi and add the panel in Studio using its displayed IP address.

**First installation erases existing Wi-Fi, pairing and panel settings.** This file is for USB installation, not Studio's firmware update button. Use normal OTA updates afterward to preserve settings. [SHA-256 checksum](https://github.com/bptworld/PixoraHQforHA/blob/main/firmware/usb/2.0.27/SHA256SUMS.txt). The combined installer has passed binary checks.

## Start here

1. Open **Displays & firmware** to connect your panel. Existing saved panels stay connected automatically.
2. For local decks and brightness controls, update the panel to **2.0.19 or newer** using the one-click **Update display** button. Keep it powered on until reconnection is verified.
3. In **Card Library**, find a card and choose **Options & add to deck**. Choose its options, then **Save in deck & download**.
4. The first deck is assigned to an unassigned selected display automatically. Choose a different **Active deck** if wanted, then press **Play deck**. Use **Save display settings** for brightness and quiet-hour changes.

The hub continues playback with the page closed. Each display has its own assigned deck. A confirmed playback error pauses the deck; uncertain writes are not retried automatically. Playback that was running normally resumes when the app restarts, including when a panel takes longer to reconnect. With panel firmware **2.0.26 or newer**, a running deck also resumes automatically after the display reboots, as soon as it reconnects. Press Play once after updating to establish the startup identifier. Explicitly paused decks stay paused. App 1.2.14 also waits through temporary read-only Wi-Fi status failures. Firmware 2.0.27 keeps reconnecting to saved Wi-Fi even if the network is unavailable during startup; a temporary outage no longer opens setup mode. An uncertain deck write stays blocked until a new panel boot is confirmed; uncertain priority messages are never replayed.

## Cards and helper files

The catalog lists **142 public Pixora cards** in Finance, Fun, Smart Home, Social, Sports, Travel, Utility and Weather. Only catalog metadata ships with the app. Executable card code is downloaded from the pinned public card-library revision when a saved deck needs it. Downloads are checked against their published size and SHA-256.

When no saved deck uses a card, the app removes that card’s specific files from the hub. **Shared helper modules, fonts and common assets stay on the hub once downloaded**, including when there are temporarily no saved cards. A dependency still required by another card is also retained. Disabling a card keeps its saved deck reference; remove it from every deck and save to discard the card.

The app downloads files before committing deck changes. Failed downloads keep the previous saved deck. API keys stay in app data and are masked in browser responses. Blank password fields keep saved values when editing or copying a deck.

Cards render on the HA hub. Clocks and local graphics work without an internet connection once installed. Live-data cards contact their own providers and may need provider credentials; availability and limits depend on those services. Public catalog thumbnails also load from the card repository. Provider-specific live results have not all been verified on physical hardware.

## Decks and previews

Create, rename, duplicate and delete decks. Reorder cards, change duration and options, or disable individual cards. Saving an edited deck keeps running decks playing and paused decks paused. A deck must be unassigned from displays before deletion.

Saved cards have locally rendered previews at the selected panel width. Animated card output is preserved and played at a bounded rate over the LAN. The browser preview is approximate; fonts and cropping depend on each card’s output.

## Displays and groups

Each display has brightness and quiet hours in the configured time zone. Set quiet brightness to **0** for a dark display. Brightness applies on the panel, including HA messages. Quiet-hour scheduling runs while its deck is playing.

**Device Groups** starts or pauses each member’s assigned deck together. Group playback uses each display’s own deck; it does not stretch artwork into a multi-panel video wall.

## My Graphics

Upload a PNG, JPEG or WebP, or open **Graphics Lab** to draw pixels and add text. Saved artwork stays on the hub and can be added to decks. Uploaded animated images currently use the first frame. Remove a graphic from all decks before deleting it.

## Home Assistant actions

The app installs its companion and registers connected panels automatically. When new companion code needs loading, open **Displays & firmware** and use the clearly labelled **Restart Home Assistant** button at a convenient time. This restarts HA; it is never performed automatically.

Each panel has a `notify` entity. Use **Send a notification message**, **Pixora LED (Local): Show card**, or **Show image card** for priority messages. The panel prevents a deck frame from overwriting an active priority message, and deck playback continues with the next card afterwards.

Use **Pixora LED (Local): Play deck** with an optional saved deck name or ID, or **Pause deck**, in HA automations. Blank deck selection uses the display’s assigned deck. HA’s native automation editor provides device, sensor, calendar and time triggers; no second rule engine or Cloud automation service is required.

## Local data and access

Decks, settings, uploaded graphics, downloaded cards and playback state live in this app’s Home Assistant data folder. Keep them in your normal HA backups. Browser access is through HA Ingress. Native HA deck actions use the panel-specific saved authorization over the internal HA app network. Card renderer subprocesses do not receive the Supervisor token.

Only S3 64×32 and 128×32 panels are supported. Both use the same user-OTA firmware image and retain the saved panel-width setting. If a 128-wide panel repeats the same image on each half or appears as 64×32, update to panel firmware 2.0.20, open **Displays & firmware → Manage displays**, choose **128 × 32**, and click **Save panel size**. The panel restarts; the app verifies its size while keeping Wi-Fi, pairing, its name and decks. Firmware source remains private; only ready-to-upload binaries are published separately.

Add this app repository: **https://github.com/bptworld/PixoraHQforHA**.

This release has local software, browser and firmware build checks. Physical-panel verification of new deck controls remains pending. No panel was flashed automatically.


## Uninstall cleanly

Before uninstalling, open LED Studio and expand **Remove Studio before uninstalling** at the bottom (also available in Displays & firmware). Type **REMOVE** and choose **Remove Studio data and HA devices**. Wait for **Cleanup complete**. This permanently removes all Studio data, downloaded cards and helpers, graphics, keys, local Studio backups, Pixora LED (Local) HA devices/entities and installed companion files. If cleanup fails, keep the app installed and use the same option again. Cleanup mode prevents devices and files from being recreated, including after an app restart.

Then uninstall **Pixora LED Studio** in **Settings → Apps** and restart Home Assistant to unload the companion actions. HA removes the app package and remaining private storage, including the small cleanup marker and Supervisor options. Panel firmware and existing HA backups are unchanged. Update any automations that referenced the removed entities.


## Local special graphics and interruptions

Use **Test** beside a special graphic setting to send a sample to the selected display or group through the normal interrupt queue. It uses the options currently shown without saving them, changing live event history, or starting a paused deck. Progress and success/error feedback appear in the dialog; render time is shown after queueing. Group tests use the same readiness check and shared animation clock as real group events.

After updating to 1.2.0, restart Home Assistant once if prompted so its notify entities use the hub queue. Existing display entities keep their identities.

- Enable a card's score/event animation options, choose its team or other required values, save the deck, and press **Play**. Event-capable cards are checked on the hub while the deck runs (approximately every 15 seconds, plus provider/render time). No Pixora Cloud account or event server is involved; live cards still contact their own data providers.
- Previewing cards and preparing ordinary deck frames do not consume events. The hub retains each card/display's event history across renderer restarts, queues new special graphics once, and keeps celebrations out of the repeating artwork cache. A first observation establishes the baseline rather than celebrating an old score.
- HA notifications and image actions go through a local, durable queue. HA messages precede waiting card events; HA messages retain their own order. The current priority item finishes before the next one. Deck artwork stops for the interrupt, then continues with the next card in the rotation. A cold card with no active content is skipped; a broken card does not stop healthy cards.
- GIF and animated WebP uploads retain their frames and delays. Special events play once and hold the final frame for any remaining event duration. Original animation delays are preserved down to 20 ms. Frames are streamed over local Wi-Fi, so physical frame rate and cross-panel timing depend on the hub, network and display; this is not a hardware frame-synchronization guarantee.
- For a card's **group/wall** event target, create a Device Group and arrange displays from left to right with **Move left**. Its artwork is rendered at the combined width, sliced for each 64/128 panel and prepared before a shared start. All members follow one animation clock; if a member cannot become ready, the entire wall graphic is skipped. Keep one intended wall group per display; if several contain it, the first matching saved group is used.
- If a physical delivery has an uncertain outcome, that display stops delivery and does not replay the item, including after an app restart. Check the display, then press **Play** to explicitly resume. An explicit busy rejection may be retried briefly because the panel confirmed it did not accept the write.

Artwork, event history and queued messages are stored only in the app's private hub storage. Pre-uninstall cleanup removes them along with the other Studio data. Waiting priority items expire after five minutes so stale messages and celebrations do not play later. Queue limits are 32 waiting items and 8 MB of encoded content per display; artwork caches retain at most 32 entries. Automatic event checking runs only while its deck is playing and outside quiet hours. Pausing a deck removes its waiting card events; an already-playing priority item finishes normally, and HA notifications remain queued.

Group walls wait until every member has finished prior messages and decoded its slice. The hub then starts one monotonic animation timeline with a short local lead; slow writes skip expired frames rather than stretching that panel’s timeline. A member that cannot become ready within 35 seconds causes the whole graphic to be skipped. An uncertain delivery stops further group writes without replay. This reduces drift; physical Wi-Fi and panel drawing latency still limit exact synchronization. Ordinary assigned decks retain their own content and rotation; group Play/Pause controls are dispatched concurrently.

## Create and import your own apps

Open **My Apps** in LED Studio to download the [AI card-creation brief](https://github.com/bptworld/PixoraHQforHA/blob/main/pixora_led_displays/Pixora-Codex-Card-Brief.md) and a [starter Python card](https://github.com/bptworld/PixoraHQforHA/blob/main/pixora_led_displays/custom_card_starter.py). Give the brief to your AI with your card idea, review the returned `.py` file, then import it in My Apps. Imported apps appear in the Card Library and can be configured and added to decks. Both 64×32 and 128×32 use the same file. Requires LED Studio 1.2.24 or later.

Custom Python runs with LED Studio’s access to files and the network: only import code you trust. The single-file importer reads metadata without running the card; rendering executes it. Custom apps stay in the HA app’s persistent data across restarts and unused-card cleanup. Download your source from My Apps to edit or share it. Remove an app from saved decks before replacing or deleting it.
