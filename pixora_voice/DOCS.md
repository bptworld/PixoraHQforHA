# Pixora Voice — local Home Assistant app

An initial implementation of a standalone hub app and native Assist conversation
agent. It uses HA state, domains, device classes, areas and aliases instead of an
LLM. No Pixora account, remote language model or cloud command transport.

**IN BETA TESTING. Keep your usual controls and assistant available.**
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
intent vocabulary, **not arbitrary HA troubleshooting knowledge**. Recent history, media controls, relative brightness, bounded thermostat changes,
and broader Planner calendars are supported as described below. General HA troubleshooting knowledge,
chained or conditional commands, security actions such as unlocking, arbitrary music catalog searches,
and date-specific repeating chore calculations remain outside this deterministic assistant. Unsupported requests do not execute an approximation.

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

## Voice triggers for Flows

1. In Home Control → Flows, add a **Voice trigger** and enter just the phrase, such as **Good night**.
2. Connect the actions, save, and enable the Flow.
3. In Pixora Voice, select **Refresh Voice triggers**. Wait for Speech-to-Phrase training to finish. Refresh again after changing phrases.
4. Say your satellite’s wake word, then the phrase: **Okay Nabu, good night**. The wake word is configured on the satellite; this feature does not change it.

This uses the paired Pixora Home Control app and existing Flow runner over the internet. Planner integration can be off. Local recognition learns up to 64 exact phrases, ignoring punctuation and capitalization, without an LLM or background polling. Anyone using a satellite can run these configured paths. Use only actions you want household speakers to invoke. Repeating the phrase restarts that matching path; independent paths continue. Pausing the Flow prevents new voice runs immediately. Commands already sent can finish. A timeout is uncertain: check Flow history before trying again. Every reply stops listening.

For this update, use **Install / update Assist integration** and restart Home Assistant once before refreshing phrases. Existing voice assistant and speaker settings remain in place.

## Expanded everyday requests

- Time/date run directly on the Yellow using HA's time zone.
- Current weather uses one Assist-exposed HA weather entity. Forecasts make one on-demand `weather.get_forecasts` call (daily or hourly), limited to 72 entries. The configured provider may need internet. Missing forecast data is not treated as “no rain.”
- Timers use HA's native timer intents, with the capturing satellite/device and original request context. The satellite must support native timers. Start, named timers, pause, resume, cancel and time remaining are supported, up to 24 hours. No private timer engine, continuous polling, scheduled device commands or auto-retries are added. Text requests without a timer-capable device explain this limitation.
- Shared, permitted devices can receive thermostat target/mode/on/off, fan percentage/low-medium-high, blind/curtain open-close-position, light color, scene activation and media play/pause/resume/stop/mute/volume commands. Play resumes existing media. Controls are checked against advertised features, thermostat min/max and zero-to-100 percentages. Window-cover commands exclude door/gate/garage classes.
- Relative brightness uses a fresh reading with a default 10-percentage-point adjustment. Thermostat changes are limited to five degrees per request. Pronouns can refer to one previously named, still-shared device after a new wake word; otherwise a unique room/device is required.
- “When did the front door last open?” reads one entity's Recorder state changes over the last 24 hours without attributes or a fabricated initial state. At most one Recorder lookup runs at a time, with a five-second answer timeout. No retained background history collector or new database is created. No recorded change means no guessed answer.
- Planner calendars support weekdays, this/next weekend, week and month, named month/day dates and ISO dates. Next personal appointments use that person's assignments, not unrelated family TV entries. Meals support today/tonight/tomorrow. Calendar search remains read-only and household shared.
- “What's the value of isKitchenMotion?” reads an existing global Flow variable through the paired Home Control connection, even with the Planner checkbox off. Boolean/number/text values are read as stored, not interpreted as a device status. No variable write is performed. Refresh Voice triggers trains up to 32 variable names; exact read requests can address any valid name in the text UI. Authenticated non-administrator users cannot read Flow variables through this assistant; household satellites have the same configured access as Voice triggers.

After updating: install/update Assist, restart HA once, Prepare added phrases, Refresh Planner phrases if enabled, and Refresh Voice triggers for variable names. Local grammar uses bounded numeric ranges and eight common named timers (pizza, pasta, tea, coffee, laundry, cooking, oven, eggs); typed timer names may be other short plain names. There is no LLM or additional always-on poller. These additions are verified with local fixtures; physical satellite and Yellow timing tests are still required after deployment.
