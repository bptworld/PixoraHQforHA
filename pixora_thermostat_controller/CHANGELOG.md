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
