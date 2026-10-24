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
