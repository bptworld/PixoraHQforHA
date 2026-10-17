# Pixora LED Displays

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
