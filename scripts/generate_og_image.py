"""Generate a 1200x630 Open Graph image for social sharing."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def load_font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load the first available font from a cross-platform candidate list."""
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


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
    font_title = load_font([
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ], 76)
    font_sub = load_font([
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ], 34)
    font_url = load_font([
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ], 26)

    # Party color bars (decorative)
    colors = ["#E53935", "#1565C0", "#43A047", "#FF8F00"]
    bar_y = 500
    bar_w = W // len(colors)
    for i, color in enumerate(colors):
        draw.rectangle([i * bar_w, bar_y, (i + 1) * bar_w, bar_y + 8], fill=color)

    # Title
    draw.text((80, 150), "PolTrends Australia", fill="white", font=font_title)

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
