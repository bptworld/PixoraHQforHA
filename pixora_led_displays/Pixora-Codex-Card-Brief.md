# Pixora LED Studio — AI Card Creator Brief for Home Assistant

Upload this file to your AI and describe the LED card you want. Ask it to return one complete UTF-8 `.py` file that follows this brief, plus a short explanation of its options and data providers.

## Where cards run

Pixora LED Studio is a Home Assistant app installed from [PixoraHQ for Home Assistant](https://github.com/bptworld/PixoraHQforHA). Python runs locally inside the LED Studio app on the HA hub. Rendered images are delivered to the LED displays over local Wi-Fi. There is no Windows Pixora server, Cloud rendering account or firmware change involved. Internet-based cards still need their data provider.

A custom app is a Python LED card, not a Home Assistant integration or a separately installed HA app. It uses the same deck player, display selection, preview and Quiet Hours as library cards.

## Import and use your card

Requires LED Studio 1.2.24 or later.

1. Open LED Studio → **My Apps**. Download this brief and the starter card there if needed.
2. Ask your AI to create or modify one Python card. Save it as a `.py` file, up to 256 KB.
3. Review the code. Custom Python runs with LED Studio's access to files and the network. A separate renderer process and metadata checks are not a security sandbox. Import only code you trust.
4. Select the file, tick the trust checkbox and press **Import app**. Import reads literal metadata without running the code.
5. Choose **Options & add to deck**. Imported cards also appear in **Card Library → My Apps** and the deck card picker. Configure options, save the deck and preview it at both supported widths before playing it.
6. To update a card, keep its CARD_ID and remove it from saved decks before importing its replacement. Download its original Python file from My Apps for editing or sharing. Deleting is also blocked while a saved deck uses it.

Custom source stays in LED Studio's persistent `/data` storage across app restarts and normal updates. Removing it from every deck does not delete the imported source. It is private to that HA installation and is not published to GitHub. Include the app's data in your normal HA backups. Removing the HA app and its data removes custom cards too.

## Required single-file contract

Use literal top-level assignments for metadata. Do not call helper functions to construct CARD_OPTIONS: the importer deliberately does not execute Python to read metadata.

```python
from io import BytesIO
from PIL import Image, ImageDraw

CARD_ID = "my_first_card"
CARD_NAME = "My First Card"
CARD_DETAIL = "A short description for the card picker."
CARD_VERSION = "1.0.0"
CARD_AUTHOR = "Your name"
CARD_OPTIONS = [
    {"key": "label", "label": "Label", "type": "text", "default": "Hello"},
]

def render(options=None):
    options = options or {}
    width = 128 if options.get("_width") == 128 else 64
    image = Image.new("RGB", (width, 32), "black")
    draw = ImageDraw.Draw(image)
    draw.text((3, 10), str(options.get("label") or "Hello")[:8], fill=(80, 200, 255))
    out = BytesIO()
    image.save(out, "PNG")
    return out.getvalue()
```

- CARD_ID: lowercase letter followed by lowercase letters, digits or underscores; up to 48 characters. Keep it stable when updating. LED Studio adds a `custom_` prefix internally so custom cards cannot replace public library files.
- CARD_NAME: required, up to 80 characters. CARD_DETAIL: up to 300 characters. CARD_VERSION: up to 32 characters. CARD_AUTHOR: up to 80 characters.
- Define a synchronous `render(options=None)` function at the top level. Return image bytes, not an Image object, filename, HTML or base64 string.
- Return a static PNG or WebP, or an animated WebP with its frame durations. Output must be at most 5 MB and animations at most 2,048 frames. Use black backgrounds and RGB output.
- For ordinary cards, an optional result dictionary is `{"body": image_bytes, "dwell_secs": 10}`. Deck items normally use the user's selected duration. Do not add legacy Cloud response headers, HTTP handlers or device commands.

## Options supported by the HA editor

CARD_OPTIONS is a literal list of up to 30 dictionaries. Keys must be unique, start with a letter and contain only letters, digits and underscores, up to 48 characters. Keys starting with `_` are reserved for runtime values.

Supported types are `text`, `password`, `number`, `checkbox`, `select`, `multiselect` and `date`. Each option needs `key`, `label` and `type`; `default` is optional. Text inputs can set an integer `maxlength` from 1 to 4096. Number options may set finite `min`, `max` and a positive `step`; minimum must not exceed maximum. Number defaults must respect the bounds and step. When step is omitted, decimal values are allowed. Checkbox defaults must be actual booleans and number defaults must be numbers. Selects and multiselects need 1–100 choices, either strings or dictionaries such as `{"value": "F", "label": "Fahrenheit"}`. A multiselect reaches render as a comma-separated string. Checkboxes reach render as booleans; numbers as numbers. Provide sensible defaults and validate all inputs inside render.

Use password options for provider tokens and API keys. Their defaults must be empty. Saved secrets stay on the HA hub and are blanked in browser state; blank values in a saved item's password field preserve its existing value. Do not hard-code secrets, use them in URLs, log them, or include them in shared source. Imported Python itself is not encrypted secret storage.

## Runtime values

The renderer supplies these reserved options; users do not configure them:

- `_width`: 64 or 128. This is the authoritative canvas width; height is always 32.
- `_target`: `matrixportal-s3-64x32` or `matrixportal-s3-128x32` for compatibility.
- `_pixora_target`: `pixora-s3` or `pixora-s3-wide` for older helpers.
- `_settings`: LED Studio defaults, including `timezone`, `timeFormat`, `temperatureUnits`, `defaultZipCode`, and configured provider settings. Use only the settings relevant to the requested card.
- `_device_id`: render context identifier. Preview is not a physical display.
- `_dwell`: requested card duration in seconds.
- `_is_prefetch`: true for ordinary preview/prefetch renders. Do not send alerts or perform write actions from render.

Render may run repeatedly, in separate processes or for previews. Module globals do not provide durable cross-render state. Do not start background threads, servers or infinite loops. Return promptly; LED Studio applies a renderer deadline. Ordinary results are cached, so do not depend on render being called every second. For changing visuals, return an animation.

## Dependencies, assets and fetching

Keep the importable custom card self-contained. Python's standard library, Pillow and aiohttp are available. Do not require pip installs, another custom module, a Windows font path, a shell command or absolute local paths. This first custom importer accepts one `.py` file, not ZIP packages or separate assets. Draw artwork with Pillow or embed small artwork in the Python file.

LED Studio also installs its verified shared public card helpers and fonts when a custom card is first used. You may use `card_utils` helpers already provided by the library, but a Pillow-only card is simplest to share. Public helpers are compatibility utilities, not proof that arbitrary custom code is sandboxed. If using public fetch helpers, declare a literal `CARD_ALLOWED_DOMAINS` list and follow their documented allowlist/timeout behavior.

Use HTTPS, short network timeouts and a clear fallback when a provider is offline or credentials are missing. Reuse provider data and honor rate limits. Do not make writes to providers from a rendering function. Never fetch metadata from the browser, create your own firmware endpoint or send frames directly to a panel. HA entities are available through LED Studio's built-in Home Assistant card; custom cards do not receive HA access tokens automatically.

## Layout and visual quality

Test real 64×32 and 128×32 layouts separately. Do not draw at one size and stretch it to fit the other. Measure text with Pillow textbbox/textlength, account for font offsets, and shorten or wrap long names and values. Keep every text box and logo inside its allocated area with a few pixels of spacing. Use legible small fonts, strong contrast, restrained colors and useful fallback artwork. A wide card should use its extra space deliberately.

Custom cards join regular decks. This simple import format does not register custom group-wall event controls or custom rules. If requesting a scoring interrupt or wall animation, use the existing library sports cards or extend and test the HA event pipeline separately; do not invent unsupported metadata or assume legacy Cloud event headers work.

## Required checks before returning a card

1. Compile the Python file and check that metadata consists of literal values.
2. Call render at `_width=64` and `_width=128`, decode the output with Pillow and verify exact dimensions and valid image data.
3. Test default options, empty inputs, long names, large values, missing credentials and provider/network failures.
4. Inspect both rendered images for clipped text, overlap, unreadable labels and stretched artwork. For animations, inspect representative frames and durations.
5. Do not run network requests or write files at module import time. Ensure render has no message-sending or other external write side effects.
6. Return the complete single-file card and instructions to import it in My Apps. Do not claim it has been physically tested unless someone verified it on a display.

## Prompt to send with this brief

> Create a Pixora LED Studio custom card for Home Assistant that shows [describe the information and appearance]. Follow the attached brief. Return one complete Python file with literal metadata and options, a render function, both 64×32 and 128×32 layouts, sensible offline behavior, and no firmware or server changes. Show previews at both sizes and explain any data-provider setup.
