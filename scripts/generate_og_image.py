"""Generate a 1200x630 Open Graph image for social sharing."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def generate_og_image(output_path: Path) -> None:
    """Create a branded OG image at 1200x630."""
    W, H = 1200, 630
    img = Image.new("RGB", (W, H), "#1a1a2e")
    draw = ImageDraw.Draw(img)

    # Gradient-ish effect: draw darker strip at top
    for y in range(H):
        r = int(26 + (22 - 26) * y / H)
        g = int(26 + (33 - 26) * y / H)
        b = int(46 + (62 - 46) * y / H)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    # Accent bar at top
    draw.rectangle([0, 0, W, 6], fill="#e94560")

    # Load fonts
    try:
        font_title = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 64)
        font_sub = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 32)
        font_url = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 24)
    except OSError:
        font_title = ImageFont.load_default()
        font_sub = font_title
        font_url = font_title

    # Party color bars (decorative)
    colors = ["#E53935", "#1565C0", "#43A047", "#FF8F00"]
    bar_y = 500
    bar_w = W // len(colors)
    for i, color in enumerate(colors):
        draw.rectangle([i * bar_w, bar_y, (i + 1) * bar_w, bar_y + 8], fill=color)

    # Title
    draw.text((80, 160), "PolTrends Australia", fill="white", font=font_title)

    # Subtitle
    draw.text(
        (80, 260),
        "Political Search Trends & Analysis",
        fill="#cccccc",
        font=font_sub,
    )

    # Tagline
    draw.text(
        (80, 320),
        "Daily Google Trends data for Australian political parties",
        fill="#999999",
        font=font_sub,
    )

    # URL
    draw.text(
        (80, 550),
        "poltrends.stewartmedia.com.au",
        fill="#e94560",
        font=font_url,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(output_path), "PNG", optimize=True)


if __name__ == "__main__":
    from config.settings import OUTPUT_DIR

    generate_og_image(OUTPUT_DIR / "og-image.png")
    print(f"OG image saved to {OUTPUT_DIR / 'og-image.png'}")
