# Pixora Insight

**Your home. Explained.** Records available HA device changes, command requests,
automation/script starts and their causal context. One standalone local app;
no companion integration, account, cloud, LLM or HA restart.

Install from **https://github.com/bptworld/PixoraHQforHA**, start the app, and open
its Web UI. Confirm **Recording locally**. Choose a device, find an action, then
open **Explain**. The recorder works with the page closed.

Default retention: 7 days / 20,000 events. Change retention and exclude noisy
entities under **History settings**. History stays on the hub and automatically
expires. Exclusions apply to future recording; mixed commands targeting an
excluded entity are omitted as a whole.

**Coverage has limits:** recording starts on connection, with no old-history
import. Gaps and unknown causes are shown explicitly. Requested commands do not
confirm success. Physical controls or private app decisions cannot be explained
unless their source reports the necessary information. Free-text/private payloads
are omitted. Device activity and presence are still private household data.

No direct LAN port, device-control endpoint, SSH or separate integration is
required. See the in-app coverage note and README for the full privacy, retention
and optional app-explanation contract.

[Brought to you by PixoraHQ.com](https://pixorahq.com/)
