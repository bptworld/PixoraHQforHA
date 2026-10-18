"""A self-contained custom LED Studio card. Import this file in My Apps."""
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

CARD_ID = "my_message"
CARD_NAME = "My Message"
CARD_DETAIL = "Your own message, fitted to a 64×32 or 128×32 display."
CARD_VERSION = "1.0.0"
CARD_AUTHOR = "Your name"
CARD_OPTIONS = [
    {"key": "message", "label": "Message", "type": "text", "default": "Hello Pixora", "maxlength": 80},
    {"key": "bright", "label": "Bright text", "type": "checkbox", "default": True},
]


def render(options=None):
    options = options or {}
    width = 128 if options.get("_width") == 128 else 64
    image = Image.new("RGB", (width, 32), "black")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    message = str(options.get("message") or "Hello Pixora").replace("\n", " ")[:80]
    while message and draw.textbbox((0, 0), message, font=font)[2] > width - 6:
        message = message[:-1]
    box = draw.textbbox((0, 0), message, font=font)
    x = (width - (box[2] - box[0])) // 2 - box[0]
    y = (32 - (box[3] - box[1])) // 2 - box[1]
    draw.text((x, y), message, font=font, fill=(80, 200, 255) if options.get("bright", True) else (40, 100, 128))
    output = BytesIO()
    image.save(output, "PNG")
    return output.getvalue()
