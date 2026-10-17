# Pixora LED Studio

Build decks on your Home Assistant hub and serve them straight to MatrixPortal S3 **64×32** and **128×32** displays over local Wi-Fi. No Pixora Cloud account or rendering server is used.

Brought to you by [PixoraHQ.com](https://pixorahq.com/).

## Start here

1. Open **Displays & firmware** to connect your panel. Existing saved panels stay connected automatically.
2. For local decks and brightness controls, update the panel to **2.0.19 or newer** using the one-click **Update display** button. Keep it powered on until reconnection is verified.
3. In **Card Library**, find a card and choose **Options & add to deck**. Choose its options, then **Save in deck & download**.
4. The first deck is assigned to an unassigned selected display automatically. Choose a different **Active deck** if wanted, then press **Play deck**. Use **Save display settings** for brightness and quiet-hour changes.

The hub continues playback with the page closed. Each display has its own assigned deck. A confirmed playback error pauses the deck; uncertain writes are not retried automatically. Playback that was running normally can resume when the app restarts.

## Cards and helper files

The catalog lists **142 public Pixora cards** in Finance, Fun, Smart Home, Social, Sports, Travel, Utility and Weather. Only catalog metadata ships with the app. Executable card code is downloaded from the pinned public card-library revision when a saved deck needs it. Downloads are checked against their published size and SHA-256.

When no saved deck uses a card, the app removes that card’s specific files from the hub. **Shared helper modules, fonts and common assets stay on the hub once downloaded**, including when there are temporarily no saved cards. A dependency still required by another card is also retained. Disabling a card keeps its saved deck reference; remove it from every deck and save to discard the card.

The app downloads files before committing deck changes. Failed downloads keep the previous saved deck. API keys stay in app data and are masked in browser responses. Blank password fields keep saved values when editing or copying a deck.

Cards render on the HA hub. Clocks and local graphics work without an internet connection once installed. Live-data cards contact their own providers and may need provider credentials; availability and limits depend on those services. Public catalog thumbnails also load from the card repository. Provider-specific live results have not all been verified on physical hardware.

## Decks and previews

Create, rename, duplicate and delete decks. Reorder cards, change duration and options, or disable individual cards. Saving an edited deck pauses its playback so changes can be reviewed before pressing Play. A deck must be unassigned from displays before deletion.

Saved cards have locally rendered previews at the selected panel width. Animated card output is preserved and played at a bounded rate over the LAN. The browser preview is approximate; fonts and cropping depend on each card’s output.

## Displays and groups

Each display has brightness and quiet hours in the configured time zone. Set quiet brightness to **0** for a dark display. Brightness applies on the panel, including HA messages. Quiet-hour scheduling runs while its deck is playing.

**Device Groups** starts or pauses each member’s assigned deck together. Group playback uses each display’s own deck; it does not stretch artwork into a multi-panel video wall.

## My Graphics

Upload a PNG, JPEG or WebP, or open **Graphics Lab** to draw pixels and add text. Saved artwork stays on the hub and can be added to decks. Uploaded animated images currently use the first frame. Remove a graphic from all decks before deleting it.

## Home Assistant actions

The app installs its companion and registers connected panels automatically. When new companion code needs loading, open **Displays & firmware** and use the clearly labelled **Restart Home Assistant** button at a convenient time. This restarts HA; it is never performed automatically.

Each panel has a `notify` entity. Use **Send a notification message**, **Pixora LED (Local): Show card**, or **Show image card** for priority messages. The panel prevents a deck frame from overwriting an active priority message, and deck playback resumes afterwards.

Use **Pixora LED (Local): Play deck** with an optional saved deck name or ID, or **Pause deck**, in HA automations. Blank deck selection uses the display’s assigned deck. HA’s native automation editor provides device, sensor, calendar and time triggers; no second rule engine or Cloud automation service is required.

## Local data and access

Decks, settings, uploaded graphics, downloaded cards and playback state live in this app’s Home Assistant data folder. Keep them in your normal HA backups. Browser access is through HA Ingress. Native HA deck actions use the panel-specific saved authorization over the internal HA app network. Card renderer subprocesses do not receive the Supervisor token.

Only S3 64×32 and 128×32 panels are supported. Both use the same user-OTA firmware image and retain the existing saved panel-width setting. Firmware source remains private; only ready-to-upload binaries are published separately.

Add this app repository: **https://github.com/bptworld/PixoraHQforHA**.

This release has local software, browser and firmware build checks. Physical-panel verification of new deck controls remains pending. No panel was flashed automatically.


## Uninstall cleanly

Before uninstalling, open LED Studio and expand **Remove Studio before uninstalling** at the bottom (also available in Displays & firmware). Type **REMOVE** and choose **Remove Studio data and HA devices**. Wait for **Cleanup complete**. This permanently removes all Studio data, downloaded cards and helpers, graphics, keys, local Studio backups, Pixora LED (Local) HA devices/entities and installed companion files. If cleanup fails, keep the app installed and use the same option again. Cleanup mode prevents devices and files from being recreated, including after an app restart.

Then uninstall **Pixora LED Studio** in **Settings → Apps** and restart Home Assistant to unload the companion actions. HA removes the app package and remaining private storage, including the small cleanup marker and Supervisor options. Panel firmware and existing HA backups are unchanged. Update any automations that referenced the removed entities.


## Local special graphics and interruptions

After updating to 1.2.0, restart Home Assistant once if prompted so its notify entities use the hub queue. Existing display entities keep their identities.

- Enable a card's score/event animation options, choose its team or other required values, save the deck, and press **Play**. Event-capable cards are checked on the hub while the deck runs (approximately every 15 seconds, plus provider/render time). No Pixora Cloud account or event server is involved; live cards still contact their own data providers.
- Previewing cards and preparing ordinary deck frames do not consume events. The hub retains each card/display's event history across renderer restarts, queues new special graphics once, and keeps celebrations out of the repeating artwork cache. A first observation establishes the baseline rather than celebrating an old score.
- HA notifications and image actions go through a local, durable queue. HA messages precede waiting card events; HA messages retain their own order. The current priority item finishes before the next one. Deck artwork pauses immediately and resumes with its remaining dwell afterward. A cold card with no active content is skipped; a broken card does not stop healthy cards.
- GIF and animated WebP uploads retain their frames and delays. Special events play once and hold the final frame for any remaining event duration. Original animation delays are preserved down to 20 ms. Frames are streamed over local Wi-Fi, so physical frame rate and cross-panel timing depend on the hub, network and display; this is not a hardware frame-synchronization guarantee.
- For a card's **group/wall** event target, create a Device Group and arrange displays from left to right with **Move left**. Its artwork is rendered at the combined width, sliced for each 64/128 panel and scheduled with a shared start time. If a display is occupied long enough to miss that start, its late slice is discarded instead of showing a wall out of phase. Keep one intended wall group per display; if several contain it, the first matching saved group is used.
- If a physical delivery has an uncertain outcome, that display stops delivery and does not replay the item, including after an app restart. Check the display, then press **Play** to explicitly resume. An explicit busy rejection may be retried briefly because the panel confirmed it did not accept the write.

Artwork, event history and queued messages are stored only in the app's private hub storage. Pre-uninstall cleanup removes them along with the other Studio data. Waiting priority items expire after five minutes so stale messages and celebrations do not play later. Queue limits are 32 waiting items and 8 MB of encoded content per display; artwork caches retain at most 32 entries. Automatic event checking runs only while its deck is playing and outside quiet hours. Pausing a deck removes its waiting card events; an already-playing priority item finishes normally, and HA notifications remain queued.
