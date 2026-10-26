## 0.1.8
- Keep door/window protection status notifications silent while the thermostat is confirmed off, including changes to the open-contact list and closed-contact restoration. Continue protection checks and activity logging, and preserve confirmations when the outdoor rule turns heating off.

## 0.1.7
- Show a compact outside temperature, selected sensor and outdoor heat-off rule status on each thermostat card. Readings use the controller units and remain visible while the rule is off or another protection blocks control; unavailable readings are never presented as current.

## 0.1.6
- Name the schedule period and target in activity, distinguish requested adjustments from HA-confirmed targets, and record period changes that need no thermostat command.
- Add per-sensor Okay/Ignore notification actions for unavailable contact/outdoor readings, persistent ignored-device tracking, and Fixed buttons to restore checks. Ignored sensors stay configured; the thermostat itself cannot be ignored.
- Preserve reselected unavailable contacts, follow HA notification service availability without polling, and show override expiry in local 12-hour time for the UI and Voice.
- Wait 60 seconds before notifying about continuously unavailable door/window readings, avoiding brief reconnect alerts. Unknown readings still block thermostat adjustments immediately; recovery cancels the pending alert.

## 0.1.5
- Display schedule and activity times in 12-hour format with AM/PM.

## 0.1.4
- Record notification recipients and full sent messages in Recent activity, including outdoor Yes/No prompts. Uncertain sends are recorded as warnings without retrying.

## 0.1.3
- Name the affected doors/windows in missing-reading and open-protection alerts, including unavailable/unknown readings and entity IDs when names are missing.

## 0.1.2
- Add thermostat Voice status, hold duration and resume-schedule requests. Refresh local phrases after updating Assist.
- Controller adds date/return-home holds, day copying, notification choices, read-only protection previews and settings backup/restore. Restored controllers are disabled.

## 0.1.1
- Fix Add thermostat and Add period on non-HTTPS local Home Assistant addresses. Show a visible message if setup cannot open.
- Voice temperature changes become timed controller overrides. Window and outdoor protection retain priority. No direct fallback on connection failure.
- Update both apps, install/update Assist in Voice setup, then restart HA once. No new speech phrases required.

## 0.1.0

- First local HA app beta: weekly heat/cool schedules, timed/next-period overrides
  and temporary holds for physical thermostat changes.
- Configurable door/window delays, heating setback, cooling pause and return to
  the current schedule/override after all contacts close.
- Outdoor heat cutoff with a return margin, notifications, and selectable
  Automatic or Ask first behavior using HA Companion Yes/No notifications.
- No response, No, expired/duplicate actions and missing readings never approve
  an outdoor heat-off request. Only a fresh, valid Yes does.
- Durable local settings and command claims; no uncertain command/notification
  replay. Admin-only HA Ingress, native capability/range checks, no cloud/LLM.
- Desktop/mobile web UI, local activity history and app icon. Live Yellow,
  thermostat and phone testing remain required before relying on this beta.
