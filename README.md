# PixoraHQ for Home Assistant

One Home Assistant app repository for PixoraHQ apps.

[Add this repository to Home Assistant](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fbptworld%2FPixoraHQforHA)

## Install

1. Open **Settings → Apps → App store → ⋮ → Repositories**.
2. Add **https://github.com/bptworld/PixoraHQforHA**.
3. Refresh the store and choose an app under **PixoraHQ for Home Assistant**.

Future apps appear when Home Assistant refreshes this repository. They are not
installed automatically. Each app keeps its own configuration, version and data.

| App | Purpose | Setup |
| --- | --- | --- |
| HAFlow | Local Home Assistant Flow editor and automation runner | [Instructions](haflow/README.md) |
| Pixora Home Control | Connect HA to Pixora Home Control, Planner and Flows | [Instructions](pixora_home_control/README.md) |
| Pixora Locator | Connect Pixora Locator with HA and import selected zones | [Instructions](pixora_locator/README.md) |
| Pixora LED Displays | Local S3 LED cards, native HA display entities and Wi-Fi updates | [Instructions](pixora_led_displays/README.md) |

Home Control and Locator retain their existing Pixora service connections.
LED Displays runs locally on the HA hub and supports S3 64x32/128x32 only.
Its initial firmware has passed compilation/software checks; physical panel and
Supervisor installation verification are pending. Firmware source is private.

## Already installed from an older repository?

The old repositories and their existing app directories remain available. Their
HA app directories are deprecated and now point here. Their code, app slugs,
versions and data layouts are not changed by that notice. Nothing is automatically
moved, uninstalled or re-paired.

HA includes the repository URL in an installed app's identity. Installing an app
from this repository creates a separate installation with separate app data.
Back up your old app and follow its setup/export instructions before moving.
Stop the old app before starting its replacement so automations and connectors
do not run twice. Keep the old installation until the replacement is verified.
Do not assume a normal update transfers data between repositories.

For HAFlow, follow the [complete Flow transfer guide](haflow/TRANSFER_FLOWS.md).

## Releases

This repository is the primary location for future HA app development/releases.
Each app has its own changelog and version. Changes to one app do not require
releasing the others. Public contents are limited to these HA apps and their
supporting documentation/tests; private server code and firmware source stay out.
