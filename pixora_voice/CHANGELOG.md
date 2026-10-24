## 0.1.10
- Voice temperature changes become timed controller overrides. Window and outdoor protection retain priority. No direct fallback on connection failure.
- Update both apps, install/update Assist in Voice setup, then restart HA once. No new speech phrases required.

## 0.1.9
- Add local time/date, configured HA weather and bounded forecasts, HA-native satellite timers, broader device controls and relative adjustments, and one-device/24-hour Recorder history questions.
- Add read-only global Flow variable answers and a bounded spoken variable vocabulary. No variable writes or new Flow engine.
- Expand shared Planner calendar dates and personal next-appointment matching. Home lookup failures stay home-specific instead of being mistaken for calendar searches.
- Add a compact capability guide with clear setup and limitations. Uses existing HA services and data, standard-library parsing, finite speech phrases and no LLM or new background polling.
- Install/update Assist, restart HA once, Prepare added phrases, Refresh Planner phrases if enabled, and Refresh Voice triggers to learn variable names. Timers require a native timer-capable satellite; weather needs an exposed weather entity; history needs Recorder. Physical Yellow/satellite verification remains required.

## 0.1.8
- Use conversational replies across home status, commands, counts, clarification, access problems, unavailable devices, Flow requests and connection failures. Answer yes/no questions directly only when the reported state supports the answer.
- Planner replies now use natural sentences for schedules, sports, TV, meals, shared lists and search results. Original shared content, dates, values and privacy boundaries are preserved.
- Keep uncertain commands explicit: check the device or Flow history before trying again. No automatic retries, extra listening, model calls or background polling are added.
- Update the Assist integration from Setup & maintenance and restart Home Assistant once to load the local reply changes. No phrase refresh is needed for this wording-only update.

## 0.1.7
- Recognize natural calendar TV requests such as “Is Fire Country on tonight?” without requiring “New Episode.” Refresh Planner phrases after installing the updated Assist integration. Short title aliases remain bounded.
- Start existing Pixora Flows with exact configured phrases such as “Good night.” Add a Voice trigger, save and enable the Flow, then use Refresh Voice triggers in this app.
- Train up to 64 local phrases without polling, an LLM or a second automation engine. Flows use your existing paired Home Control connection and require internet; the Planner checkbox is independent.
- Voice commands acknowledge queue admission, use normal run history and restart the matching path when retriggered. Paused flows cannot run; uncertain commands are never retried automatically.
- Anyone using a satellite can start the configured voice paths. Authenticated non-administrator HA users cannot invoke these server automations through this assistant.
- After updating the app, install/update the Assist integration, restart Home Assistant once, then refresh Voice triggers. Keep your satellite’s configured wake word (for example, “Okay Nabu”).

## 0.1.6

- Search shared Planner information for unanswered read-only questions instead of requiring a fixed topic or team name. Keep local device commands, permissions and uncertainty handling unchanged, and stop listening after every reply.
- Search all shared calendar events by their saved title/team, including manually added and imported entries. If no information matches, reply: “Sorry, I can't find the information you're looking for.”
- Include playing/play questions and saved calendar titles in the bounded local speech phrases. Refresh Planner phrases after updating the companion integration to train the new spoken forms.
- Recognize teams named in manual calendar fixtures, preserve upcoming/date/person constraints during fallback, distinguish calendar reservations from meal plans, and search full note text with short matching excerpts. Treat command words inside a read-only question as search terms.

## 0.1.5

- Simplify Voice descriptions, setup text and documentation while retaining the beta label.

## 0.1.4

**In Beta Testing.**

- One request per wake word: stop listening after every answer, clarification or failure. Say the wake word again for a follow-up within 90 seconds; never automatically keep listening. Brief context is isolated by speaker/user and capped at 64 hints in RAM.
- Read-only follow-ups re-read current permitted state; state duration uses HA’s current reported state timestamp, not invented history. Planner schedule questions support “And tomorrow?”.
- More natural question phrasing and room awareness. Unqualified temperature/humidity requests use the speaker's room; never substitute another room's sensor.
- Preserve capability matching, Assist exposure and permissions. Unavailable sensors and stale/unknown Planner presence remain unknown.
- Friendly bounded Planner/command failure replies, without automatic retries of uncertain commands.
- On-demand recent Assist timing view: recognition after speech ends, lookup and speech preparation. No background polling, extra trace recording, large models or persistent cache. Speech preparation is not actual speaker playback time.
- Prepare a small owned additional question vocabulary from Setup & maintenance, preserving user phrase files.

## 0.1.3

**In Beta Testing.**

- Allow the local recognizer time to restart and distinguish a saved vocabulary from a restart acknowledgment timeout. Include HA action descriptions.
- Use the listening HA hub timezone when Planner has no saved household timezone, so today/tomorrow answers work without extra setup.

## 0.1.2

**In Beta Testing.**

- Redesigned mobile-friendly Web UI, example prompts, collapsible setup, and a custom home/microphone app icon.
- More natural, shorter spoken replies.
- Polite requests, spoken brightness percentages, and room phrases.
- Actual cooling activity, filtered group status/counts, and plural room light commands.
- Preserve numbered room identities and reject ambiguous pronoun controls.
- Expanded bounded local speech grammar; no extra model or background polling.

- Optional read-only Planner answers through the existing paired HA connector, with household-shared Calendar entries from every source, meals, lists and current home status. Bounded household speech phrases, opt-out and manual refresh; no LLM or additional pairing.

# 0.1.1

**IN BETA TESTING.**

- Load the standard HA app environment for internal API access. Include additional local recognizer phrases for the first beta questions without replacing existing user sentences.

# 0.1.0

**IN BETA TESTING.**

- Initial local-only home questions and controls with capability-aware matching, satellite room context and room-wide light commands. No cloud or LLM.
- Explicit companion integration installation with backups, Assist exposure and HA entity permissions.
