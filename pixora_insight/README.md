# Pixora Insight

**Your home. Explained.** One standalone, local Home Assistant app recording
device activity and available causal evidence. No companion integration, account,
cloud service, LLM or HA restart is required.

[Brought to you by PixoraHQ.com](https://pixorahq.com/)

## Install

1. Add **https://github.com/bptworld/PixoraHQforHA** to Settings → Apps → App store
   → Repositories, if it is not already present.
2. Refresh the store, install **Pixora Insight**, start it and open its Web UI.
3. Confirm **Recording locally**, then choose a device or search for its name,
   entity ID or action. Open **Explain** for the recorded details and context links.

It begins recording on connection, independently of the browser. Existing device
controls, automations and Pixora apps continue working normally. Insight never
sends device commands. It does not install another integration or require access
to app containers, SSH, private configuration files or the Recorder database.

## What gets recorded

- Entity state changes and allowlisted control/temperature attributes.
- HA service requests, including available entity, device and area targets.
- Automation triggers and script starts, with HA context and parent-context links.
- App-reported decisions when an app emits the optional `pixora_insight` event.
- Coverage changes: app starts, disconnects, reconnects and writer-queue loss.

State changes confirm what an entity reported, not necessarily what the physical
equipment did. A service request is always labelled **requested**, never successful
merely because it was received. Causes come from HA context links, never nearby
timestamps. Without evidence, the explanation says the cause is unknown.

This includes ordinary HA and Pixora-originated commands that HA exposes. Existing
apps do not automatically expose their private conditions, delays or cancelled
steps. Blocked actions, physical remote controls and proprietary integration
internals can only be explained when their source provides evidence. No app can
promise to capture literally every influence on a physical device through HA.

Device/area mappings are a snapshot of the HA registry. Registry changes refresh
on subsequent events at most once per 30 seconds. Unresolved targets, domain-wide
`all`, floor/label targets, over 256 mapped entities per event, and missing
permissions limit per-device matching; the request still records without guessing.
Recording starts at installation/connection. Events during a disconnect or before
installation are not reconstructed. Old HA traces and Recorder history are not
imported. It does not predict future actions or inspect automation conditions.

## Lightweight local history

One local HA WebSocket subscribes only to selected event types, not every event
and not unchanged `state_reported` updates. The initial catalog/registry loads once
per connection; there is no device polling. The UI refreshes only while visible
and can pause following activity. Sensor value changes still record; exclude very
noisy entities in **History settings** if needed.

Default retention is **7 days / 20,000 events**, whichever limit is reached first.
Choose 1–14 days and 1,000–50,000 events. SQLite uses a 64 MiB main-database page
budget plus bounded batches and its write-ahead journal. The bounded 2,048-event
queue batches up to 100 events per write. Writes and queries run off the event
loop. On overflow or storage failure, the app reports a recording gap rather than
blocking HA or pretending the log is complete. Under storage pressure, oldest
records may be removed before the normal retention limit to resume recording.

Back up the app using HA's normal app backup. Its local `insight.sqlite` database
and settings live in `/data`. History expires automatically; reducing retention
removes older records. Exclusions affect future recording, including mixed
commands containing excluded entities; existing records expire normally.

## Privacy and access

The Web UI and API require HA ingress. No direct LAN port is published. Only the
HA app page may change history settings. There is no device-command endpoint.
All assets stay local. No secret, token, raw event body, media contents, notification
message, GPS coordinate attribute, camera image or user ID is stored. Free-text
entity state is omitted while the occurrence of its change may still be recorded.
Numeric sensor values and a short allowlist of device attributes are recorded;
explicitly named credential/location entities have values omitted. Device/entity
names, entity IDs, presence home/away and activity times remain private household
information stored on the hub. Administrator access and backups should be treated
accordingly. Custom app explanations are caller-provided text; their producers
must not put private messages, credentials or location details in a reason.

## Optional app explanation contract

Apps may fire this existing HA event through HA's normal local API:

```json
{
  "event_type": "pixora_insight",
  "data": {
    "entity_id": ["climate.hallway"],
    "source": "Thermostat Controller",
    "outcome": "blocked",
    "reason": "The monitored window is open; the scheduled heat increase was withheld."
  }
}
```

Use outcomes `requested`, `confirmed`, `blocked`, `waiting` or `cancelled`.
Populate the normal HA event context when available. Insight labels these as
**app-reported explanations**, not independently verified evidence. Emitting this
event is optional; normal HA activity records without changes to other apps.

## Evidence reference

Uses HA's documented [WebSocket event subscriptions](https://contributors.home-assistant.io/core/internals/websocket-api/)
and [context data model](https://contributors.home-assistant.io/data/reference/data-model/).
What HA exposes can vary by integration; an automation starting does not prove
its conditions passed or its actions completed.
