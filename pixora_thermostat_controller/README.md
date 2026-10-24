# Pixora Thermostat Controller (Beta)

Weekly schedules, temporary holds and local thermostat protection running on your
Home Assistant hub. **Beta: verify your equipment and notification behavior before
relying on unattended control.**

[Brought to you by PixoraHQ.com](https://pixorahq.com/)

## Install and set up

1. Add **https://github.com/bptworld/PixoraHQforHA** in Settings -> Apps -> App
   store -> Repositories. Install **Pixora Thermostat Controller (Beta)**.
2. Start the app and open its Web UI. No token entry, pairing or HA restart is
   required. It uses Home Assistant's internal API through Supervisor.
3. Add a thermostat. Choose its temperature unit as shown in HA, then add weekly
   schedule periods. A period continues until the next one, including overnight.
4. Optionally select doors/windows, the open delay, heating setback and closed
   return delay. Choose the notification recipient and their existing HA service.
5. Optionally choose an outdoor temperature sensor/weather entity and heat limit.
   Choose **Automatic** or **Ask first**. Configure a return margin to avoid
   switching repeatedly at the limit.
6. Enable the controller and save. New controllers are disabled until you enable
   them. Check the current target, reason and recent activity in the app.

Use only one schedule controller for each physical thermostat. The app supports
up to 12 controllers with one thermostat assigned to each. No control code runs
in the browser: closing the Web UI does not stop schedules or protection.

## Doors and windows

If an individual selected contact remains open for your configured delay, the app
lowers heating to the setback, without raising an already lower heating target.
Cooling pauses. After all selected contacts are confirmed closed for the return
delay, the active schedule or unexpired override resumes. Missing readings are
not treated as closed. During an outage the app sends no new commands.

An open-contact timer that was not yet satisfied restarts its full observation
after an app restart/reconnect. An already active protection is remembered.
Disabling or removing a controller leaves the physical thermostat at its current
settings; it does not silently undo a setback.

## Outdoor rule: ask or automatic

- **Automatic:** above your outdoor limit, turn heating off and notify. The app
  does not turn cooling on as a side effect; heat/cool mode is paused as a whole.
- **Ask first:** send “It's over 50 degrees F outside. Should I turn the heat off?”
  with **Yes / No** actions, using the configured limit/unit. Requires an existing
  HA Companion `notify.mobile_app_...` destination. Choose the intended person's
  phone explicitly; the app does not guess which device belongs to someone.
- **Only Yes approves heat-off.** The app checks current outdoor temperature again
  before accepting Yes. No, missing data or no answer never approves it. Buttons
  expire after ten minutes. Duplicate, expired and unrelated actions are ignored.
  No/expiry suppresses another prompt for the same warm-weather episode.
- An automatic or approved heat lockout clears when temperature falls to the
  limit minus your return margin. The current schedule/override then resumes.

HA Companion notification delivery and callback access depend on your existing
phone/HA setup. The app has no Pixora Cloud connection, account or LLM, but native
phone push delivery may require internet supplied by HA's notification transport.

## Overrides and failures

Apply a timed override (30 minutes, one, two or four hours) or hold until the next
schedule period. Physical thermostat/other HA changes create a configurable
temporary hold. Protection remains active during overrides. A physical off
setting is respected.

Targets must fit the thermostat's reported modes, capabilities and min/max
temperatures. The app changes native thermostat targets; it does not switch
relays directly or replace the equipment's compressor/freeze protections.

The app writes its command intent before sending it and waits for the thermostat
state to confirm the target. An uncertain result is **never retried**. Inspect the
actual thermostat and use **I've checked the thermostat** to explicitly resume.
Notifications are also claimed before sending and are not blindly retried.

## Local storage and resource use

Configuration, overrides, active protection, command claims and a bounded recent
history live in the app's `/data/controller.json`, written atomically. Include app
data in HA backups. Corrupt saved data fails closed rather than being reset.

One local WebSocket watches HA state/action events, with a small filtered catalog.
A five-second local timer checks schedule boundaries and contact delays. There
is no cloud polling, large model, custom integration, public port or Node runtime.
The admin-only Web UI is available through HA Ingress. Settings have revision
checks to prevent another browser from overwriting newer edits.

## Updates

Install from the canonical repository above from the beginning. Normal app
updates retain the same slug and `/data` storage; no reinstall is required.

This app is separate from Pixora Home Control and server Flows. It does not edit
or replace existing Flows, thermostats, helpers or HA automations.
