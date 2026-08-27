"""
Generates scripts/dmg-assets/background.png, the picture Finder shows
behind the DMG install window (see package-dmg.sh).

Layout (must stay in sync with the *_ICON_X / *_ICON_Y / WINDOW_* values
in package-dmg.sh):

  Row 1 (primary install flow):
      [ JobTracker Hub.app ]  --arrow-->  [ Applications ]

  Row 2 (secondary, optional):
      [ Learn More ]   [ User Guide ]
      (.webloc -> portfolio page)   (.pdf -> bundled user guide)

Coordinates: confirmed against a real DMG build (screenshot pixel
measurements, 2026-08-26) that Finder's "set position of item to
{x,y}" places the icon's CENTER at (x,y), 1:1 with this image's own
pixel grid -- no offset. An earlier version of this script assumed a
+40px offset that was never actually verified on macOS; it was wrong,
which is why the row-2 icons rendered higher than the art expected and
overlapped the "Optional extras" caption. Keep *_ICON_X / *_ICON_Y in
package-dmg.sh equal to the *_center_y values drawn below.

Contrast fix: Finder draws each icon's filename label itself, in
whatever color the *system* light/dark appearance dictates (white text
in a dark-appearance Finder window, black text in a light-appearance
one) -- that color is not something this script controls. Painting a
very dark background behind those labels means the label text becomes
unreadable in whichever appearance we didn't happen to guess right, so
each icon row gets a translucent mid-tone "plate" behind it: roughly
mid-gray gives ~4.5:1 contrast against both black and white text,
which is the standard workaround since there's no per-item label-color
API available to a background image / AppleScript combo. Confirmed
legible against real black Finder label text in the same screenshot.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Kept in sync with WINDOW_W / WINDOW_H / *_ICON_X / *_ICON_Y in
# package-dmg.sh -- those *_ICON_Y values ARE the *_center_y values
# used below (confirmed 1:1, see module docstring).
W, H = 660, 600
PORTFOLIO_URL = "willmaddock.github.io/dev/projects/jobtracker-hub"

img = Image.new("RGB", (W, H), (15, 23, 42))  # #0F172A, matches app's dark navy
draw = ImageDraw.Draw(img)

# subtle vertical gradient for depth
top = (15, 23, 42)
bottom = (10, 16, 30)
for y in range(H):
    t = y / H
    r = int(top[0] + (bottom[0] - top[0]) * t)
    g = int(top[1] + (bottom[1] - top[1]) * t)
    b = int(top[2] + (bottom[2] - top[2]) * t)
    draw.line([(0, y), (W, y)], fill=(r, g, b))


def load_font(size, bold=False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for c in candidates:
        try:
            return ImageFont.truetype(c, size)
        except Exception:
            continue
    return ImageFont.load_default()


def centered_text(y, text, font, fill, shadow=True):
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    x = (W - w) / 2
    if shadow:
        draw.text((x + 1, y + 1), text, font=font, fill=(5, 8, 15))
    draw.text((x, y), text, font=font, fill=fill)


def label_plate(cx, top_y, bottom_y, width, radius=14, alpha=0.34):
    """A translucent mid-gray rounded plate, blended into the current
    background, that keeps a Finder-drawn filename label readable
    regardless of whether Finder is rendering it in light or dark mode."""
    plate_rgb = (148, 163, 184)  # slate-400: readable under black or white text
    x0, x1 = cx - width / 2, cx + width / 2
    # sample-and-blend per pixel would be slow; the background gradient
    # is nearly flat locally, so blend against the color at plate center
    base = img.getpixel((int(cx), int((top_y + bottom_y) / 2)))
    blended = tuple(int(base[i] * (1 - alpha) + plate_rgb[i] * alpha) for i in range(3))
    draw.rounded_rectangle([x0, top_y, x1, bottom_y], radius=radius, fill=blended)


title_font = load_font(22, bold=True)
sub_font = load_font(14)
caption_font = load_font(13, bold=True)
url_font = load_font(13, bold=True)

# --- Title -----------------------------------------------------------
centered_text(38, "Drag JobTracker Hub into Applications", title_font, (236, 240, 246))
centered_text(68, "then open it from your Applications folder", sub_font, (176, 186, 200))

# --- Row 1 plate + arrow ----------------------------------------------
# Matches APP_ICON_Y / APPS_ICON_Y = 170 in package-dmg.sh (confirmed
# real icon center, not a guess -- see docstring).
row1_icon_center_y = 170
row1_plate_top = row1_icon_center_y - 75      # headroom for the icon glyph
row1_plate_bottom = row1_icon_center_y + 95   # room for the label below it
label_plate(180, row1_plate_top, row1_plate_bottom, width=190)   # under app icon+label
label_plate(480, row1_plate_top, row1_plate_bottom, width=190)   # under Applications icon+label

left_x, right_x = 180, 480
shaft_color = (74, 158, 255)  # #4a9eff, matches app's accent blue
draw.line([(left_x + 70, row1_icon_center_y), (right_x - 70, row1_icon_center_y)],
          fill=shaft_color, width=4)
ax, ay, head_size = right_x - 70, row1_icon_center_y, 14
draw.polygon([(ax, ay - head_size), (ax + head_size + 6, ay), (ax, ay + head_size)],
             fill=shaft_color)

# --- Divider caption between the two rows -----------------------------
# Must clear row1_plate_bottom above and leave a real gap before
# row2_plate_top below -- this is exactly what overlapped in the first
# real build (see docstring), so keep generous margins on both sides.
centered_text(290, "Optional extras", caption_font, (203, 211, 224))

# --- Row 2 plate: Learn More + User Guide ------------------------------
# Matches LEARN_ICON_Y / GUIDE_ICON_Y = 420 in package-dmg.sh.
row2_icon_center_y = 420
row2_plate_top = row2_icon_center_y - 75
row2_plate_bottom = row2_icon_center_y + 95
label_plate(240, row2_plate_top, row2_plate_bottom, width=150)  # Learn More
label_plate(420, row2_plate_top, row2_plate_bottom, width=150)  # User Guide

# --- Portfolio URL footer, always visible even if the .webloc icon is --
# ever stripped/blocked by Gatekeeper or an unusual Finder view setting.
centered_text(row2_plate_bottom + 24, PORTFOLIO_URL, url_font, (125, 190, 255))

out_path = Path(__file__).resolve().parent / "dmg-assets" / "background.png"
out_path.parent.mkdir(parents=True, exist_ok=True)
img.save(out_path)
print(f"saved {out_path}")
