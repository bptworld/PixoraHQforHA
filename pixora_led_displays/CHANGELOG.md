# 1.2.25

- Reject custom files that cannot compile, invalid render signatures and option limits/defaults that break the editor. Apply numeric limits in custom card forms. Audit import, replacement, real deck delivery, saved options and restart recovery for 64×32 and 128×32.

# 1.2.24

- Import trusted custom Python cards in My Apps, configure them and add them to normal decks. Download the HA AI creator brief, starter and original custom source. Keep imported apps across restarts and unused-card cleanup; protect apps referenced by saved decks from replacement or deletion.

# 1.2.22

- Add Do not show to scoring-animation targets, including basketball baskets, goals and runs. Disabled scoring events keep score history current and ordinary cards updating without interrupting playback. Available for already downloaded cards; Test is disabled for a hidden graphic.

# 1.2.21

- Recover running decks automatically after an uncertain card delivery. Reconnect using read-only status checks, let any accepted frame expire, then continue with the next card without resending the uncertain frame. Manual pauses and priority-message delivery errors remain respected.

# 1.2.20

- Replace cards with a local dim clock during Quiet Hours, using the selected timezone and time format. Existing zero-brightness quiet schedules now use 10% so the clock stays visible.
- Resume the deck at the next card after Quiet Hours without saving a pause. Suppress queued sports/card events during quiet schedules and respect the schedule boundary for long cards.
- Preserve playing and paused states when display settings are saved. Reconcile an uncertain brightness response using reported panel state instead of treating it as a failed card delivery.

# 1.2.19

- Fit special-graphic text to measured pixel bounds at 64x32 and 128x32, with separate portrait, logo and caption lanes. Correct clipped sports captions, long fighter/player names, order totals and weather labels.
- Keep wall headlines clear of player details and images, remove effects drawn over portraits, and show correct inning captions. Check both three-device wall layouts: 64+128+64 and 64+64+64.
- Use the same layouts for live events, warmed graphics and Test buttons, including downloaded league-card aliases. Invalidate older cached renders automatically while preserving animation durations and interrupt rotation.
- Keep existing downloaded card files intact; no card removal, redownload or firmware change is required.

# 1.2.18

- Apply the new controls to already downloaded cards and existing decks automatically, including cards whose original metadata had no group selector. No card removal or redownload is needed.

- Load actual provider conferences and divisions for all public sports standings cards, with drill-down through nested groups and exact saved group rendering.
- Add provider division discovery and filtering for Sleeper, ESPN Fantasy and Yahoo Fantasy standings. Leagues without divisions keep their league table.
- Keep older selections readable, preserve saved private-league credentials on the hub and do not substitute another division when a selection is unavailable.

# 1.2.17

- Show a neutral No active content preview for temporarily inactive cards instead of a broken-preview error. Keep retry controls below error text.

- Make paused displays and decks stand out with a red status badge, red selected-display border and red device-picker outline in both themes. Show Paused instead of a stale card title after playback stops.

# 1.2.16

- Keep priority animation bodies, provider data and public image assets warm on the hub between isolated card workers, with bounded storage and provider freshness limits.
- Warm configured wall scenes during live card checks. Prepare installed-card tests and their display slices before Test is pressed; share in-progress preparation and reuse confirmed display sizes.
- Cache finished wall slices and ready-to-send RGB frames. Decode off the event loop and remove the PNG encode/decode round trip before each frame upload.
- Preserve fresh scorer/player artwork and one-shot interrupt history. Cache entries contain artwork only and never replay deliveries.

# 1.2.15

- Include the selected team's provider logo and colors in special-graphic tests, and use the full wall scenes for group tests. Report when provider artwork is unavailable.

- List each assigned display group by name in special-graphic targets. Save the selected group ID and route tests and automatic events to that group; ambiguous older targets require a specific choice.

- Show numbered left-to-right positions when creating and viewing display groups. Arrange displays with Move left and Move right before saving, and preserve pending selections during other refreshes.

# 1.2.14

- Keep running decks waiting through temporary read-only Wi-Fi status failures instead of permanently pausing them. Uncertain writes remain blocked and are never retried on the same startup.
- Pair with firmware 2.0.27, which keeps retrying saved Wi-Fi at startup and uses a true 8 MHz panel output on both 64x32 and 128x32.

# 1.2.13

- Add a Show display preview checkbox that remembers its choice in this browser and stops loading previews while hidden.

- Keep display names and sizes on separate lines after clicking a display button.

- Resume running decks when a display restarts, using firmware 2.0.26 startup identifiers. Explicitly paused decks stay paused; uncertain priority messages are never replayed.
- Wait for displays that are still offline when the HA app starts, without permanently pausing their saved playback.

# 1.2.12

- Preserve an edited panel-size choice when a background firmware check finishes, including after focus moves to Save.
- Show Preparing the first card after a successful Play request instead of displaying Paused while rendering begins.

# 1.2.11

- Recover from transient read-only panel status failures with bounded checks. Never retry an uncertain display write.
- Use confirmed panel dimensions for event checks instead of repeatedly polling the panel. Report event-check failures without incorrectly claiming playback continues after a connection failure.

# 1.2.10

- Show failed display actions with the display name and actual cause. Keep each affected display’s error visible instead of incorrectly reporting every failure as a group action.

- Refresh and persist confirmed panel dimensions and firmware after USB flashing or size changes. Update setup controls and the Studio device screen from the selected panel without changing its name, pairing or playback.

# 1.2.9

- Move display name, panel size and removal into a visible Manage displays section at the top of Displays & firmware. Remove manual card sending from this setup page. Keep the management and firmware display pickers synchronized.

# 1.2.8

- Serialize hub connections to each panel during firmware transfer and restart verification so deck traffic waits while other displays continue.
- Verify the running version after an unconfirmed upload without resending firmware. Keep delivery blocked if verification fails.
- Distinguish a failed status check from a firmware upload failure, record update stages in the app logs, and refresh saved firmware details after verification.

# 1.2.7

- Add a Display picker inside Panel firmware, synchronized with the main picker. Lock both during updates so checks, automatic updates and manual uploads use the intended display.

# 1.2.6

- Add Panel size under Displays & firmware → Display settings. Correct a 128×32 panel that reports 64×32 without resetting Wi-Fi, pairing, names or decks. Requires panel firmware 2.0.20. Verify the restart before updating saved dimensions.

# 1.2.5

- Compare Cloud wall timing with local delivery. Wait for every group member to finish prior messages and prepare artwork before starting one shared timeline.
- Correct animation drift after slow Wi-Fi writes by skipping expired frames; skip the whole wall if a member cannot become ready. Stop group delivery after an uncertain write without replay.
- Start group controls concurrently and validate panel dimensions before wall delivery.

# 1.2.4

- Add Test buttons beside special graphic settings. Send sample graphics through the real local interrupt queue without changing saved options or event history.
- After interrupts, continue with the next card in the deck rotation instead of resuming or restarting the interrupted card.

# 1.2.3

- Audit all 27 special-event cards and panel/wall artwork variants. Preserve flight landing history, complete local flight snapshots, retain valid events when ordinary rendering fails, and keep event history when only deck duration changes.
- Keep ordinary movie slideshows playable when they use the no-replay flag; poll launch events frequently enough for the short countdown window.
- Monitor scoring animations for cards that delegate event detection to shared helpers, including NCAA Football, CFL and UFL.

# 1.2.2

- Clear the HA restart notice automatically when setup is ready.
- Keep playing decks running when saved; paused decks stay paused. Apply edited card options on the next card transition.
- Audit all 142 cards at both display widths. Fix width-aware fallback artwork for Commodities, Currency Rates and Sector Heat; support longer scrolling animations such as Daily Bible Verse. Download missing Disney park artwork with its cards.

# 1.2.1

- Download dynamically loaded sibling animation modules for College Football, CFL, UFL, College Baseball, College Softball and NCAA Hockey. Fix first-use rendering without requiring another sports card to be installed.

# 1.2.0

- Add hub-local event history, structured card results, special-graphic queues, play-once event delivery and interruption-aware deck resumption. Route HA notifications through the hub queue.
- Preserve animation timing and animated uploads. Fan group-wall event artwork into ordered display slices.
- Companion 1.2.0 requires one HA restart to load queued notification delivery.

- Skip broken cards for the current playback session while other cards continue. Show skipped card names; pause clearly if none can play. Never retry uncertain panel writes.

- Outline disabled deck cards in red.

- Keep bounded rendered artwork on the hub, serve last good artwork immediately, and refresh it in the background like Cloud. Preserve cache isolation by card options, dimensions, settings and renderer revision.

- Prepare the next card during playback and retain artwork across deck loop transitions instead of briefly showing Waiting. Renew long static cards before the panel timeout.

- Add Pro Sports, College Sports and Fantasy submenus to the Card Library and Decks card picker, matching the Cloud grouping.

# 1.1.4

- Fix standalone card previews and playback when Heartbeat is the first downloaded card.
- Show preview loading and readable failure messages with a manual retry option. Separate card names from timing details.

# 1.1.3

- Fix card downloads by hashing exact public Git blobs, independent of Windows line endings. Preserve integrity checks and identify any failed file.

- Deepen Light theme blues, strengthen borders and highlight selected controls in blue.
- Correct garbled separators, dimensions and punctuation in Studio.

# 1.1.2

- Add confirmed pre-uninstall cleanup for Studio data, downloaded files, companion files and HA display devices. Prevent recreation after cleanup starts and report incomplete cleanup for retry.

# 1.1.1

- Add remembered Light (blue) and Dark (Planner Midnight) themes across Studio and display tools.
- Browse, search and add cards directly inside Decks.
- Show immediate action progress, visible card-dialog errors and sticky completion feedback.

- Reduce header height and spacing on desktop and tablets.
- Rename the app and HA sidebar entry to Pixora LED Studio. Existing app identity, displays, decks and settings are preserved.

# 1.1.0

- Redesign the local app around a 142-card catalog, editable saved decks, per-display playback and previews.
- Download and verify only cards used by saved decks. Remove unused card-specific files; keep shared helpers, fonts and common assets on the hub.
- Add device groups, brightness, quiet hours, local uploads and a simple Graphics Lab.
- Add native HA Play/Pause deck actions and automatic companion registration. HA messages interrupt decks and playback resumes afterwards.
- Use local S3 firmware 2.0.19 for deck priority, brightness and reboot controls. Firmware source stays private.

# 1.0.8

- Reconnect automatically after a one-click firmware update to restore saved pairing and the Waiting screen.
- Confirm the running version after restart and refresh the installed-version text. Show an unverified outcome clearly without resending firmware.

# 1.0.7

- Load Home Assistant’s container environment before starting the app, restoring Supervisor discovery and the HA restart button.
- Hide the restart button when HA API access is unavailable and show an actionable error.

# 1.0.6

- Check published S3 firmware and offer one-click download, verification and local installation.
- Show installed/latest versions and preview labels; preserve manual file installation under advanced controls.

# 1.0.5

- Install companion updates automatically at app startup.
- Register connected displays with HA automatically using saved pairing details; update existing connections without duplicate entities.
- Replace manual setup steps with clear status and a single explicit HA restart button when needed.

# 1.0.4

- Audit pairing, reconnecting, card acknowledgements, HA reconfiguration and safe companion installation.
- Keep action feedback beside its button and refresh local setup instructions.

# 1.0.3

- Add Rename and Remove controls for saved displays, with removal confirmation and durable changes.

- Show connection progress and a clear success/error message beside Connect display. Clear the name and IP only after success; keep them on failure and select the connected display for sending.

- Remove the unnecessary Important notice and migration wording from this new app’s Information page.

# 1.0.2

**IMPORTANT — This is the current app from PixoraHQ for Home Assistant.**

**App repository: `https://github.com/bptworld/PixoraHQforHA`**

Add this repository once in **Settings → Apps → App store → ⋮ → Repositories** to find all PixoraHQ Home Assistant apps and their updates.

**LED Displays runs locally on your HA hub and sends directly over Wi-Fi to S3 64x32 and 128x32 panels. No Cloud account is needed.** This app update does not install panel firmware automatically.

Brought to you by [PixoraHQ.com](https://pixorahq.com/).

- Publish an app update so existing installations receive the bold Information-page notice and setup instructions. No automatic migration or device actions.

# Changelog

## 1.0.1

- Add the PixoraHQ.com credit to app information and documentation and the app interface.

