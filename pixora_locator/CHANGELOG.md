# Changelog

## 1.5.0

- Added Battery, Charging, Speed, Distance from Home, Location Health, and Battery Unrestricted sensors to each phone device.
- Calculate straight-line distance using Home Assistant's Home zone, with miles/mph or kilometers/km/h units.
- Update all sensor states together using the existing location feed, without additional phone GPS polling.
- Keep missing measurements unavailable rather than reporting misleading zero values. Battery Unrestricted reports Android battery-optimization exemption; unsupported phones remain unavailable.

## 1.4.0

- Changed migration to export selected Home Assistant zones only.
- Ensured no location, arrival, or departure history is imported; new Places start fresh and existing matches remain unchanged.
- Added verifiable file integrity and a stable Home Assistant source identity for safe retries.
- Added visible preparation feedback while the zone file is created.

## 1.3.0

- Added a one-time zone migration exporter to the Pixora Locator Home Assistant page.
- Exports selected Home Assistant zones in a versioned `.pixora` file.
- Keeps Home Assistant credentials and unrelated entities out of the downloaded migration file.

## 1.2.0

- Replaced the single attribute-heavy Location sensor with separate visible Place, Latitude, Longitude, GPS Accuracy, Since, Movement, Sharing Mode, and Last Report sensor rows on each phone device.
- Reused the existing Location entity as Place so upgrades do not leave a duplicate legacy sensor behind.
- Marked every location-detail sensor unavailable when its phone stops sharing or disappears from the current feed.

## 1.1.0

- Added a Location sensor for each phone with current Place, Place-since time, motion, sharing mode, latitude, longitude, GPS accuracy, nearby area, and report timestamps.
- Fixed Home Assistant device firmware versions so they update after every Pixora Locator App upgrade.
- Bumped the App version so Home Assistant shows the available update in the App store.

## 1.0.3

- Corrected every installation guide so the pairing token is saved before the Home Assistant App is started.

## 1.0.2

- Upgraded base-image packages during builds and restricted container vulnerability enforcement to patchable operating-system packages.

## 1.0.1

- Added a dedicated Home Assistant App page with connection state, device status, last sync, and setup guidance.
- Kept the page available when the pairing token is missing or invalid so configuration errors are visible.

## 1.0.0

- Initial Home Assistant App release.
- Secure, revocable pairing with Pixora Locator.
- Managed trackers through Home Assistant's built-in Mobile App integration.
- Current-location-only synchronization with automatic startup and recovery.
