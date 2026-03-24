"""Generate Grok Manager icon (256x256 multi-size .ico + 64x64 tray PNG)."""
from PIL import Image, ImageDraw, ImageFont
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))


def _draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = max(size // 16, 2)
    r = max(size // 5, 4)

    # Gradient background: top #1A6DFF -> bottom #0D47A1
    for y in range(pad, size - pad):
        t = (y - pad) / max(size - 2 * pad - 1, 1)
        cr = int(26 * (1 - t) + 13 * t)
        cg = int(109 * (1 - t) + 71 * t)
        cb = int(255 * (1 - t) + 161 * t)
        draw.line([(pad, y), (size - pad - 1, y)], fill=(cr, cg, cb, 255))

    # Rounded rectangle mask
    mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([pad, pad, size - pad - 1, size - pad - 1],
                         radius=r, fill=255)
    img.putalpha(mask)

    # Lightning bolt shape (stylized)
    cx, cy = size / 2, size / 2
    s = size * 0.28
    bolt = [
        (cx - s * 0.15, cy - s * 1.0),
        (cx + s * 0.45, cy - s * 1.0),
        (cx + s * 0.05, cy - s * 0.1),
        (cx + s * 0.55, cy - s * 0.1),
        (cx - s * 0.15, cy + s * 1.1),
        (cx + s * 0.15, cy + s * 0.15),
        (cx - s * 0.35, cy + s * 0.15),
    ]
    draw.polygon(bolt, fill=(255, 255, 255, 240))

    # "G" letter overlay (small, bottom-right)
    try:
        fsize = max(size // 4, 10)
        font = ImageFont.truetype("arial.ttf", fsize)
    except (OSError, IOError):
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), "G", font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    gx = cx + s * 0.3
    gy = cy + s * 0.5
    # Shadow
    draw.text((gx - bbox[0] + 1, gy - bbox[1] + 1), "G",
              fill=(0, 0, 0, 80), font=font)
    draw.text((gx - bbox[0], gy - bbox[1]), "G",
              fill=(255, 255, 255, 200), font=font)

    return img


def generate() -> tuple[str, str]:
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [_draw_icon(s) for s in sizes]

    ico_path = os.path.join(OUT_DIR, "assets", "icon.ico")
    png_path = os.path.join(OUT_DIR, "assets", "icon_tray.png")
    os.makedirs(os.path.join(OUT_DIR, "assets"), exist_ok=True)

    # Save .ico with multiple sizes
    images[-1].save(ico_path, format="ICO",
                    sizes=[(s, s) for s in sizes],
                    append_images=images[:-1])

    # Save 64x64 PNG for tray
    images[sizes.index(64)].save(png_path, format="PNG")

    return ico_path, png_path


if __name__ == "__main__":
    ico, png = generate()
    print(f"ICO: {ico}")
    print(f"PNG: {png}")
