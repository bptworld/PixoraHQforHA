## 0.1.4

**In Beta Testing — not ready for everyday use.**

- One request per wake word: stop listening after every answer, clarification or failure. Say the wake word again for a follow-up within 90 seconds; never automatically keep listening. Brief context is isolated by speaker/user and capped at 64 hints in RAM.
- Read-only follow-ups re-read current permitted state; state duration uses HA’s current reported state timestamp, not invented history. Planner schedule questions support “And tomorrow?”.
- More natural question phrasing and room awareness. Unqualified temperature/humidity requests use the speaker's room; never substitute another room's sensor.
- Preserve capability matching, Assist exposure and permissions. Unavailable sensors and stale/unknown Planner presence remain unknown.
- Friendly bounded Planner/command failure replies, without automatic retries of uncertain commands.
- On-demand recent Assist timing view: recognition after speech ends, lookup and speech preparation. No background polling, extra trace recording, large models or persistent cache. Speech preparation is not actual speaker playback time.
- Prepare a small owned additional question vocabulary from Setup & maintenance, preserving user phrase files.

## 0.1.3

**In Beta Testing — not ready for everyday use.**

- Allow the local recognizer time to restart and distinguish a saved vocabulary from a restart acknowledgment timeout. Include HA action descriptions.
- Use the listening HA hub timezone when Planner has no saved household timezone, so today/tomorrow answers work without extra setup.

## 0.1.2

**In Beta Testing — not ready for everyday use.**

- Redesigned mobile-friendly Web UI, example prompts, collapsible setup, and a custom home/microphone app icon.
- More natural, shorter spoken replies.
- Polite requests, spoken brightness percentages, and room phrases.
- Actual cooling activity, filtered group status/counts, and plural room light commands.
- Preserve numbered room identities and reject ambiguous pronoun controls.
- Expanded bounded local speech grammar; no extra model or background polling.

- Optional read-only Planner answers through the existing paired HA connector, with household-shared Calendar entries from every source, meals, lists and current home status. Bounded household speech phrases, opt-out and manual refresh; no LLM or additional pairing.

# 0.1.1

**IN BETA TESTING — not ready for everyday use.**

- Load the standard HA app environment for internal API access. Include additional local recognizer phrases for the first beta questions without replacing existing user sentences.

# 0.1.0

**IN BETA TESTING — not ready for everyday use.**

- Initial local-only home questions and controls with capability-aware matching, satellite room context and room-wide light commands. No cloud or LLM.
- Explicit companion integration installation with backups, Assist exposure and HA entity permissions.
