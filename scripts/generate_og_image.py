"""Open Graph images (1200x630) rendered from the latest data."""
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS = Path(__file__).parent.parent / "site" / "fonts"
W, H = 1200, 630
BG = (9, 13, 21)
TEXT = (237, 240, 246)
MUTED = (136, 146, 165)
ACCENT = (182, 156, 255)
COLORS = {"ALP": "#F0524A", "LIB": "#3D8BFD", "NAT": "#F2C230", "GRN": "#3FCB6E", "PHON": "#FF8A1F",
          "LNP": "#3D8BFD", "ONP": "#FF8A1F"}
NAMES = {"ALP": "Labor", "LIB": "Liberal", "NAT": "Nationals", "GRN": "Greens", "PHON": "One Nation"}


def _inter(size: int, weight: str = "Regular"):
    try:
        f = ImageFont.truetype(str(FONTS / "Inter.ttf"), size)
        f.set_variation_by_name(weight)
        return f
    except (OSError, ValueError):
        return ImageFont.load_default(size)


def _serif(size: int, italic: bool = False):
    try:
        return ImageFont.truetype(str(FONTS / ("InstrumentSerif-Italic.ttf" if italic else "InstrumentSerif-Regular.ttf")), size)
    except OSError:
        return ImageFont.load_default(size)


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _canvas() -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    glow = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(glow)
    d.ellipse([-260, -320, 560, 300], fill=(48, 38, 92))
    d.ellipse([760, -260, 1460, 260], fill=(22, 44, 86))
    d.ellipse([380, 460, 1100, 980], fill=(52, 32, 14))
    glow = glow.filter(ImageFilter.GaussianBlur(140))
    img = Image.blend(img, glow, 0.9)
    return img


def _brand(d: ImageDraw.ImageDraw):
    x, base = 72, 92
    for i, (code, hgt) in enumerate([("ALP", 18), ("LIB", 30), ("GRN", 22), ("PHON", 40)]):
        d.rounded_rectangle([x + i * 13, base - hgt, x + i * 13 + 8, base], radius=3, fill=_rgb(COLORS[code]))
    d.text((x + 66, base - 34), "PolTrends", font=_inter(32, "SemiBold"), fill=TEXT)
    d.text((x + 66 + d.textlength("PolTrends ", font=_inter(32, "SemiBold")), base - 34), "Australia",
           font=_inter(32, "Regular"), fill=MUTED)


def _wrap(d, text, font, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if d.textlength(trial, font=font) <= width:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def generate_og_image(output_path: Path, summary: dict | None = None, model: dict | None = None,
                      kind: str = "national") -> None:
    img = _canvas()
    d = ImageDraw.Draw(img)
    _brand(d)
    d.text((W - 72, 66), "poltrends.stewartmedia.com.au", font=_inter(22, "Medium"), fill=MUTED, anchor="ra")

    if kind == "victoria" and model and model["average"]["tpp"]["ALP"] is not None:
        tpp = model["average"]["tpp"]
        d.text((72, 150), f"VICTORIA 2026  ·  {model['days_to_go']} DAYS TO GO", font=_inter(22, "SemiBold"), fill=ACCENT)
        title = "Coalition in front." if tpp["LNP"] > tpp["ALP"] else "Labor in front."
        d.text((72, 186), title, font=_serif(104), fill=TEXT)
        d.text((72, 300), "One Nation in the mix." if (model["average"]["primary"].get("ONP") or 0) >= 15 else "",
               font=_serif(104, italic=True), fill=_rgb(COLORS["ONP"]))
        y = 452
        d.text((72, y), f"{tpp['LNP']}", font=_inter(64, "Bold"), fill=_rgb(COLORS["LNP"]))
        x = 72 + d.textlength(f"{tpp['LNP']}", font=_inter(64, "Bold")) + 18
        d.text((x, y + 20), "Coalition  v", font=_inter(26, "Medium"), fill=MUTED)
        x += d.textlength("Coalition  v", font=_inter(26, "Medium")) + 18
        d.text((x, y), f"{tpp['ALP']}", font=_inter(64, "Bold"), fill=_rgb(COLORS["ALP"]))
        x += d.textlength(f"{tpp['ALP']}", font=_inter(64, "Bold")) + 18
        d.text((x, y + 20), "Labor  ·  two-party preferred poll average", font=_inter(26, "Medium"), fill=MUTED)
    elif summary:
        leader = summary["leader"]
        share = summary["stats"][leader]["share"]
        lead_name = NAMES.get(leader, leader)
        d.text((72, 150), f"NATIONAL SEARCH INTEREST  ·  WEEK TO {date.fromisoformat(summary['period']['end']).strftime('%-d %b').upper()}",
               font=_inter(22, "SemiBold"), fill=ACCENT)
        verb = "owns" if share >= 50 else "leads"
        font = _serif(110)
        line1 = f"{lead_name} {verb}"
        d.text((72, 184), line1, font=font, fill=TEXT)
        d.text((72, 300), "the conversation." if verb == "owns" else "the search race.", font=_serif(110, italic=True),
               fill=_rgb(COLORS.get(leader, "#B69CFF")))
        # share bar
        x0, x1, y = 72, W - 72, 470
        total = sum(summary["stats"][c]["share"] for c in summary["ranking"]) or 100
        x = x0
        for c in summary["ranking"]:
            wseg = (x1 - x0) * summary["stats"][c]["share"] / total
            d.rounded_rectangle([x, y, x + max(wseg - 4, 4), y + 22], radius=8, fill=_rgb(COLORS.get(c, "#888")))
            x += wseg
        x = x0
        for c in summary["ranking"]:
            label = f"{NAMES.get(c, c)} {summary['stats'][c]['share']:.0f}%"
            d.ellipse([x, y + 46, x + 14, y + 60], fill=_rgb(COLORS.get(c, "#888")))
            d.text((x + 22, y + 40), label, font=_inter(24, "Medium"), fill=TEXT)
            x += d.textlength(label, font=_inter(24, "Medium")) + 60
    else:
        d.text((72, 200), "Who is Australia", font=_serif(110), fill=TEXT)
        d.text((72, 316), "searching for?", font=_serif(110, italic=True), fill=ACCENT)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(output_path), "PNG", optimize=True)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from config.settings import OUTPUT_DIR, PROCESSED_DIR, load_latest_file

    _, s = load_latest_file(PROCESSED_DIR, "weekly_analysis.json")
    _, vs = load_latest_file(PROCESSED_DIR, "weekly_analysis.json", subdir="victoria")
    _, m = load_latest_file(PROCESSED_DIR, "seat_model.json", subdir="victoria")
    generate_og_image(OUTPUT_DIR / "og-image.png", summary=s, model=m, kind="national")
    generate_og_image(OUTPUT_DIR / "og-victoria.png", summary=vs, model=m, kind="victoria")
    print("OG images written")
