## 0.1.4
- Simplify History settings: select excluded entities in one list and use one Restore button; show only device/display exclusions below.

## 0.1.3
- Add explicit restore buttons for excluded entities, devices and app displays.
- Add Exclude device for all entities registered to an HA device, including future entities, with restoration through History settings.
- Allow excluding app-reported LED displays by app and display name, retaining earlier history and allowing restoration in History settings. Remove stray null from explanations without entity targets.

## 0.1.2
- Accept named app-only operations and exact command-context origins from all Pixora HA command producers, including indirect scene/group actions.
- Explain recorded Pixora Flow trigger/run origins using exact HA command-context reports from the existing Home Control connector, including reports that arrive after the device change.

## 0.1.1
- Add an Exclude entity button to explanations, preserving current history settings and earlier records.

## 0.1.0
- First standalone local Insight app: HA-reported state/attribute changes, requested commands, automation/script starts and causal explanations using HA contexts.
- Search by device/entity or action, inspect linked evidence and distinguish unknown causes from confirmed reports.
- Bounded local SQLite history, retention controls, exclusions and visible disconnect/overflow/storage gaps. Records independently of the browser.
- Ingress-only UI, private-payload filtering and an optional HA event contract for app-reported decisions; no companion integration, cloud or LLM.
