"""
Regenerates docs/guide-src/images/dmg-install-window.png -- the
illustration used in the User Guide's "Installing the macOS desktop
app" section.

This is a *static mockup* for the documentation only. It is not what
package-dmg.sh produces: the real DMG's look comes from Finder
rendering scripts/dmg-assets/background.png (see gen_bg.py) with the
real .app/.webloc/.pdf icons layered on top by the OS. This script
draws stand-in icon glyphs + labels directly, at fixed, readable
colors, so the guide has a picture to show without needing a real Mac
to take a screenshot on.

Kept in the repo (rather than run once and thrown away) so the guide's
illustration can be regenerated after Learn More / User Guide-copy
UI is added.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent
ICON_PATH = REPO_ROOT / "assets" / "icon.iconset" / "icon_128x128@2x.png"
OUT_PATH = REPO_ROOT / "docs" / "guide-src" / "images" / "dmg-install-window.png"

W, H = 660, 600
TITLEBAR_H = 28

img = Image.new("RGB", (W, H + TITLEBAR_H), (15, 23, 42))
draw = ImageDraw.Draw(img)

# fake window titlebar, like a real Finder window
draw.rectangle([0, 0, W, TITLEBAR_H], fill=(230, 230, 232))
for i, color in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
    draw.ellipse([14 + i * 20, 9, 24 + i * 20, 19], fill=color)
tb_font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
tb_font = ImageFont.truetype(tb_font_path, 13)
title = "JobTracker Hub"
tw = draw.textlength(title, font=tb_font)
draw.text(((W - tw) / 2, 7), title, font=tb_font, fill=(40, 40, 42))

body = Image.new("RGB", (W, H), (15, 23, 42))
bd = ImageDraw.Draw(body)
top, bottom = (15, 23, 42), (10, 16, 30)
for y in range(H):
    t = y / H
    bd.line([(0, y), (W, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))


def font(size, bold=False):
    p = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    return ImageFont.truetype(p, size)


def centered(y, text, f, fill, shadow=True):
    w = bd.textlength(text, font=f)
    x = (W - w) / 2
    if shadow:
        bd.text((x + 1, y + 1), text, font=f, fill=(5, 8, 15))
    bd.text((x, y), text, font=f, fill=fill)


def plate(cx, top_y, bottom_y, width, alpha=0.34):
    plate_rgb = (148, 163, 184)
    base = body.getpixel((int(cx), int((top_y + bottom_y) / 2)))
    blended = tuple(int(base[i] * (1 - alpha) + plate_rgb[i] * alpha) for i in range(3))
    bd.rounded_rectangle([cx - width / 2, top_y, cx + width / 2, bottom_y], radius=14, fill=blended)


def label(cx, y, text, f, fill=(240, 244, 248)):
    w = bd.textlength(text, font=f)
    bd.text((cx - w / 2, y), text, font=f, fill=fill)


title_font = font(22, bold=True)
sub_font = font(14)
caption_font = font(13, bold=True)
label_font = font(13)
url_font = font(13, bold=True)

centered(38, "Drag JobTracker Hub into Applications", title_font, (236, 240, 246))
centered(68, "then open it from your Applications folder", sub_font, (176, 186, 200))

row1_cy = 170  # matches APP_ICON_Y/APPS_ICON_Y in package-dmg.sh (confirmed real center)
plate(180, row1_cy - 75, row1_cy + 95, 190)
plate(480, row1_cy - 75, row1_cy + 95, 190)

# arrow
shaft_color = (74, 158, 255)
bd.line([(250, row1_cy), (410, row1_cy)], fill=shaft_color, width=4)
bd.polygon([(410, row1_cy - 14), (430, row1_cy), (410, row1_cy + 14)], fill=shaft_color)

# app icon (real icon asset)
if ICON_PATH.exists():
    app_icon = Image.open(ICON_PATH).convert("RGBA").resize((104, 104))
    body.paste(app_icon, (180 - 52, row1_cy - 52), app_icon)
else:
    bd.rounded_rectangle([180 - 52, row1_cy - 52, 180 + 52, row1_cy + 52], radius=22, fill=(30, 41, 59))

# Applications folder glyph
fx, fy = 480, row1_cy
bd.rounded_rectangle([fx - 50, fy - 34, fx + 50, fy + 40], radius=10, fill=(120, 170, 240))
bd.rounded_rectangle([fx - 50, fy - 46, fx - 4, fy - 30], radius=6, fill=(120, 170, 240))
bd.polygon([(fx - 16, fy + 2), (fx + 16, fy + 2), (fx + 6, fy - 22), (fx - 6, fy - 22)], fill=(235, 242, 250))
bd.rectangle([fx - 4, fy - 6, fx + 4, fy + 18], fill=(235, 242, 250))

label(180, row1_cy + 64, "JobTracker Hub.app", label_font)
label(480, row1_cy + 64, "Applications", label_font)

centered(290, "Optional extras", caption_font, (203, 211, 224))

row2_cy = 420  # matches LEARN_ICON_Y/GUIDE_ICON_Y in package-dmg.sh
plate(240, row2_cy - 75, row2_cy + 95, 150)
plate(420, row2_cy - 75, row2_cy + 95, 150)

# Learn More glyph: a simple globe/link circle
lx, ly = 240, row2_cy
bd.ellipse([lx - 40, ly - 40, lx + 40, ly + 40], outline=(120, 190, 255), width=5)
bd.ellipse([lx - 40, ly - 16, lx + 40, ly + 16], outline=(120, 190, 255), width=3)
bd.line([(lx, ly - 40), (lx, ly + 40)], fill=(120, 190, 255), width=3)
bd.arc([lx - 20, ly - 40, lx + 20, ly + 40], 90, 270, fill=(120, 190, 255), width=3)
bd.arc([lx - 20, ly - 40, lx + 20, ly + 40], 270, 90, fill=(120, 190, 255), width=3)

# User Guide glyph: a document with folded corner + lines
gx, gy = 420, row2_cy
bd.rectangle([gx - 34, gy - 46, gx + 34, gy + 46], fill=(240, 244, 248))
bd.polygon([(gx + 14, gy - 46), (gx + 34, gy - 26), (gx + 14, gy - 26)], fill=(190, 200, 214))
for i, ly2 in enumerate([gy - 8, gy + 6, gy + 20]):
    bd.rectangle([gx - 22, ly2, gx + (14 if i < 2 else 2), ly2 + 5], fill=(120, 130, 148))

label(240, row2_cy + 64, "Learn More", label_font)
label(420, row2_cy + 64, "User Guide", label_font)

centered(row2_cy + 95 + 24, "willmaddock.github.io/dev/projects/jobtracker-hub", url_font, (125, 190, 255))

img.paste(body, (0, TITLEBAR_H))
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
img.save(OUT_PATH)
print(f"saved {OUT_PATH}")
