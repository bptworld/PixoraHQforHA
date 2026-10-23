# Pixora Voice — local Home Assistant app

An initial implementation of a standalone hub app and native Assist conversation
agent. It uses HA state, domains, device classes, areas and aliases instead of an
LLM. No Pixora account, remote language model or cloud command transport.

**IN BETA TESTING — not ready for everyday use. Keep your usual controls and assistant available.**
Matching and adapter tests use fixture devices. A container build, native HA
integration load, speech recognition coverage and physical satellite tests are
still required before calling this a verified voice release.

## The first acceptance cases

| Request | Source / behavior |
|---|---|
| Is the front door open? | Door/contact binary sensor; never a lock |
| Is the front door locked? | Lock entity; never a contact sensor |
| Are there any windows open? | Window-class contacts across the home; unavailable readings disclosed |
| Is the heat on? | Thermostat `hvac_action`; distinguishes actively heating, idle and unknown |
| What's the temperature in here? | Listening satellite's HA area; dedicated temperature sensor preferred |
| Turn on the ceiling light | Listening satellite's area; asks if ambiguous |
| Turn off all kitchen lights | All exposed, permitted kitchen light entities, regardless of speaker room |

English initially. Also supports humidity, numeric battery readings, motion /
occupancy, light brightness and on/off queries and controls. This is a growing
intent vocabulary, **not arbitrary HA troubleshooting knowledge**. Historical
questions, automation explanations, calendars, media, relative changes, chained
commands, security actions such as unlocking, and temperature setpoint changes
are not implemented yet. Unsupported requests do not execute an approximation.

## Install from the permanent app repository

Add **https://github.com/bptworld/PixoraHQforHA** to the Home Assistant app store,
install **Pixora Voice (Beta)**, start it and open its Web UI. Install from this
repository for a stable app identity and normal updates. Do not configure the
temporary local copy for everyday use.

The app provides an explicit **Install / update Assist integration** action. This
copies only its own `pixora_voice` custom component into HA's configuration folder,
backing up prior versions in the app's `/data/integration-backups`. It does not
restart HA automatically, change other integrations, or change voice pipelines.
Restart HA once, add **Pixora Voice** under Devices & services, then select the
agent in your voice assistant. Keep this agent responsible for matching rather
than putting another conversation agent in front of it.

An app alone cannot register a native conversation entity in HA Core. The small
bundled custom integration supplies that entry point and runs the shared matching
engine directly on the hub. The app is the installation/setup and testing UI;
it does not poll a remote server or need a browser left open.

## Local speech and satellites

Use a local wake word, local Speech-to-Phrase or Whisper, and local Piper speech.
Speech-to-Phrase is the first option to evaluate on Yellow because it is light
enough for modest hardware, but accepts a constrained phrase vocabulary. Its
grammar must include our questions and device aliases. Extending the agent does
not automatically extend the recognizer's vocabulary. Whisper supports broader
speech and requires a real latency test on the particular Yellow hardware.
Neural speech recognition / synthesis is allowed; there is no language model
interpreting or answering home requests.

Assign each Satellite1 / ESPHome Assist satellite to the correct HA area. Context
comes from the **satellite that captured the request**, not an assumed phone
location or whichever speaker happened to play audio. Missing room context asks
for a room. An explicit room overrides the speaker. Text testing in the app has
no satellite context; test “in here” on the physical satellite.

## Permissions and behavior

- Only entities exposed to Assist are eligible. Respect the calling HA user's
  read and control permissions; satellites without a user use Assist exposure.
- Device capability is a hard filter before name matching. Offline and unknown
  states never become false/closed/off readings.
- Commands are sent once through HA services with the original request context.
  A failed acknowledgment is reported as uncertain and never blindly retried.
- Clarifications are bounded, expire after two minutes, and are scoped by
  conversation, user and originating device. State and permissions are read again
  for the follow-up.
- The UI is available through authenticated HA ingress only, with admin access
  required. No LAN command port, developer credentials or stored home-state logs.

Run offline checks from the repository root: `python -m unittest discover -s tests -p "voice_test_*.py" -v`.
Tests require aiohttp for the app installer import; the matcher is standard-library
only. The HA adapter is contract-tested with fixture HA APIs. Physical satellite and speech accuracy testing is ongoing during beta.

Official architecture references: [conversation entity](https://contributors.home-assistant.io/core/entities/conversation/),
[app communication](https://contributors.home-assistant.io/apps/guides/communication/),
[local Speech-to-Phrase](https://www.home-assistant.io/blog/2025/02/13/voice-chapter-9-speech-to-phrase/).

Brought to you by [PixoraHQ.com](https://pixorahq.com/).


### Optional Pixora Planner answers
Enable **Integrate with Pixora Planner** in the Voice app to reuse the existing paired Pixora Home Control connection. No new login or pairing is needed. Update both the Voice app/native integration and the Pixora server before enabling. Local device controls and speech remain local; Planner answers require internet, without an LLM.

Ask about a named person's schedule, Calendar items (including events added by other apps), saved sports games/broadcasts, meals, shared open chores, groceries, pantry, notes, messages, lists, countdowns, alarms and routines. Presence answers use current shared household location and report unknown when stale or unavailable. Room speakers have no verified person identity, so answers use household-shared information only. Private records and separate Budget, Student, Live, Connect and Home Control features are excluded; their shared Calendar entries remain included. This is read-only access; make changes in Planner.

Enabling prepares a small household-name/team vocabulary and restarts Speech-to-Phrase once. Use **Refresh Planner phrases** after renaming people or changing followed teams. Only `pixora_voice_planner.yaml` is generated; existing user phrase files are preserved. Access is disabled immediately when unchecked. Unsupported or ambiguous questions ask for clarification rather than guessing. Date-specific repeating chore calculations are not yet supported.


### One request per wake word

Pixora Voice stops listening after every answer, including clarification or failure.
To ask a follow-up, say **“Okay Nabu” again**, then “How long has it been open?”,
“Is it still open?” or “And tomorrow?” after a Planner schedule/calendar question.
Brief hints expire after 90 seconds, isolated by speaker and HA user (or Web UI
conversation), capped at 64 entries in RAM. There is no automatic continued
listening. Cancel with “Never mind”. New full questions replace old context.
All readings and permissions are checked again. Duration describes how long HA
has reported the current state, not an inferred history while HA was offline.
Pronoun commands never use remembered device targets; name the device to control it.
Unqualified temperature/humidity requests use the speaker's HA area; if that
area is unknown, say the room name in your next request. Explicit rooms take
precedence. Unavailable readings and stale Planner presence remain unknown.

After updating, use **Install / update Assist integration** and restart HA once.
Use **Prepare added phrases** under Setup & maintenance to write the small owned
`pixora_voice_language.yaml` and restart Speech-to-Phrase. Wait for training to
finish. Your own sentences and Planner vocabulary are preserved. Keep Amy Medium
and normal speaking pause settings unchanged. No new model or background poller.

Open **Response timing → Load recent timings** to read up to five existing
Pixora Assist traces on demand. Recognition is measured from detected speech end
to recognized text; lookup covers local or Planner handling. Speech preparation
may be deferred or cached and is **not** time to audible playback. Missing stages
show “not recorded”. Only numeric timings, assistant name and timestamp reach the
browser; no transcripts, answers, audio URLs or tokens. No extra traces are
recorded or stored. If HA timing is unavailable, use Voice assistants Debug.
Failed Planner requests and uncertain device commands produce a bounded spoken
explanation and are never blindly retried.
