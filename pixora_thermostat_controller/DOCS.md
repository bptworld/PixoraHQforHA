# Pixora Thermostat Controller

**Beta testing.** Local schedules, overrides, door/window setbacks and outdoor
heat limits. [Brought to you by PixoraHQ.com](https://pixorahq.com/).

Install from **https://github.com/bptworld/PixoraHQforHA** to retain the app's
identity and local data through future updates. No temporary repository or
custom integration is needed. Start the app and choose **Open Web UI**.

New controllers start disabled. Add a thermostat and schedule first, then enable
it deliberately. Select opening sensors, delays, setback and the intended
person's notification destination. Outdoor protection offers **Automatic** or
**Ask first**; no response never turns the heat off. Ask first requires an HA
Companion mobile-app notification service. Existing hardware/HA protection
settings continue to apply.

For the complete setup, behavior and failure/recovery guide, see the included
[README](README.md). The same guide is summarized in the app's **How your
controller works** section. You do not need a Pixora account or a cloud service.

Disabling or stopping this app leaves thermostats at their current settings.
Restore normal settings at the thermostat if necessary. Do not run competing
schedule automations. Keep native freeze/equipment protections configured.

### Voice thermostat overrides
Update both Pixora Voice and Pixora Thermostat Controller. Use Voice's Setup & maintenance to install/update Assist, then restart Home Assistant once. Temperature requests such as "Set the thermostat to 72 degrees" create an override for the controller's configured manual-hold duration. Relative changes work when a current target is readable. Window/door and outdoor protections remain active; the schedule resumes after expiry. Single-temperature requests require a heat or cool schedule/override, rather than off or heat/cool range mode. Use controller settings for managed thermostat mode/on/off changes. Disabled controllers reject voice overrides. Assist exposure, speaker room and user control permissions still apply.

Voice climate commands require the running Thermostat Controller app to check ownership. An explicit unmanaged response permits ordinary HA control; a missing response never permits a direct fallback or automatic retry. No cloud, LLM, added background polling or continued listening.

### Lightweight thermostat tools
Controller periods can be named (Wake up, Away, Bedtime). Copy a source day to another day or all weekdays; destination periods are replaced in the unsaved editor. Save applies the change.
Vacation holds end at a selected date (within one year); the browser's local time zone is used for date entry. Away holds watch one explicitly selected HA person and end only after a known away state followed by home. Unknown presence never ends the hold. All protection rules retain priority.
Choose protection/restoration, unavailable-sensor and command-failure alerts independently. Ask-first Yes/No requests remain necessary for approval. Alerts are claimed once per observed issue; uncertain delivery is not retried.
Test protections runs a copy of current rules, observations and state without saving runtime, sending notifications or changing equipment. Disabled controllers preview as disabled; pending commands and missing readings remain visible. The preview is based on current data, not a guarantee of future equipment behavior.
Download settings backup exports schedules, entity references, notification choices and names, without runtime holds, approvals or history. Restore validates the file and replaces settings with every controller disabled and runtime cleared. Review before enabling.
Voice: “Why is the heat off?”, “What is the thermostat status?”, “How long is the thermostat override?” and “Resume the thermostat schedule.” Name the room when needed. Update both apps, update Assist, restart HA once, then Prepare added phrases. Each request still ends listening. Status/resume uses the existing on-demand local event bridge; no new background service, model or cloud dependency is added.
