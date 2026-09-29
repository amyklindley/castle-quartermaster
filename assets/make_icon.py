"""Draw the bot's avatar: a gold castle in a round badge with CASTLE QUARTERMASTER around the rim.

Writes icon.svg, then renders icon.png (1024x1024) with headless Edge.  python assets/make_icon.py
"""
from __future__ import annotations

import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

NAVY, INNER, GOLD, CREAM, SHADOW = "#16203a", "#22335a", "#d9ab3f", "#f2d27a", "#101830"
C = 512


def merlons(x0: float, x1: float, top: float, w: float, h: float) -> str:
    """Crenellations: evenly spaced blocks starting and ending flush with the wall's edges."""
    n = max(2, round((x1 - x0) / (2 * w)) + 1)
    gap = (x1 - x0 - n * w) / (n - 1)
    return "".join(f'<rect x="{x0 + i * (w + gap):.1f}" y="{top - h}" width="{w}" height="{h + 1}"/>' for i in range(n))


def castle() -> str:
    ground = 735
    parts = [
        # side towers, curtain wall, central keep
        f'<rect x="292" y="420" width="112" height="{ground - 420}"/>', merlons(292, 404, 420, 24, 34),
        f'<rect x="620" y="420" width="112" height="{ground - 420}"/>', merlons(620, 732, 420, 24, 34),
        f'<rect x="400" y="500" width="224" height="{ground - 500}"/>', merlons(400, 624, 500, 26, 30),
        f'<rect x="452" y="345" width="120" height="{ground - 345}"/>', merlons(452, 572, 345, 24, 34),
        # ground
        f'<rect x="262" y="{ground}" width="500" height="22" rx="6"/>',
    ]
    details = [
        # gate with a portcullis hint, arrow slits, keep window
        f'<path d="M470 {ground} V640 A42 42 0 0 1 554 640 V{ground} Z" fill="{SHADOW}"/>',
        *[f'<rect x="{x}" y="640" width="5" height="{ground - 640}" fill="{INNER}"/>' for x in (490, 509, 528)],
        *[f'<rect x="{x}" y="{y}" width="16" height="46" rx="8" fill="{SHADOW}"/>' for x, y in
          ((340, 480), (340, 590), (676, 480), (676, 590))],
        f'<path d="M497 460 V420 A15 15 0 0 1 527 420 V460 Z" fill="{SHADOW}"/>',
        # flag
        f'<rect x="509" y="235" width="6" height="80" fill="{CREAM}"/>',
        f'<path d="M515 238 L585 258 L515 280 Z" fill="{GOLD}"/>',
    ]
    return f'<g fill="{CREAM}">{"".join(parts)}</g>' + "".join(details)


def ring_text() -> str:
    top_r, bottom_r = 398, 452   # baselines: top text grows outward, bottom text grows inward
    top = f"M {C - top_r} {C} A {top_r} {top_r} 0 0 1 {C + top_r} {C}"
    bottom = f"M {C - bottom_r} {C} A {bottom_r} {bottom_r} 0 0 0 {C + bottom_r} {C}"
    style = f'font-family="Cinzel, Georgia, serif" font-weight="700" fill="{CREAM}" text-anchor="middle"'
    dots = "".join(f'<path d="M{x} {C - 13} L{x + 13} {C} L{x} {C + 13} L{x - 13} {C} Z" fill="{GOLD}"/>'
                   for x in (C - 425, C + 425))
    return (f'<defs><path id="top" d="{top}"/><path id="bottom" d="{bottom}"/></defs>'
            f'<text {style} font-size="74" letter-spacing="7"><textPath href="#top" startOffset="50%">'
            f'CASTLE QUARTERMASTER</textPath></text>'
            f'<text {style} font-size="52" letter-spacing="10"><textPath href="#bottom" startOffset="50%">'
            f'CRAFT · GATHER · BANK</textPath></text>' + dots)


def svg() -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" width="1024" height="1024">
<style>@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@700&amp;display=block');</style>
<rect width="1024" height="1024" fill="{NAVY}"/>
<circle cx="{C}" cy="{C}" r="500" fill="{NAVY}" stroke="{GOLD}" stroke-width="14"/>
<circle cx="{C}" cy="{C}" r="476" fill="none" stroke="{GOLD}" stroke-width="3" opacity=".6"/>
<circle cx="{C}" cy="{C}" r="372" fill="{INNER}" stroke="{GOLD}" stroke-width="10"/>
{ring_text()}
{castle()}
</svg>"""


def main() -> None:
    out_svg, out_png = HERE / "icon.svg", HERE / "icon.png"
    out_svg.write_text(svg(), "utf-8")
    html = HERE / "_render.html"
    html.write_text(f'<html><body style="margin:0;background:#000">{svg()}</body></html>', "utf-8")
    subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                    "--window-size=1024,1024", "--virtual-time-budget=5000", f"--screenshot={out_png}",
                    html.as_uri()], check=True, capture_output=True)
    html.unlink()
    print(out_png)


if __name__ == "__main__":
    main()
