"""Draw the bot's avatar: a gold castle in a round badge with CASTLE QUARTERMASTER around the rim.

Writes icon.svg, then renders icon.png (1024x1024) with headless Edge.  python assets/make_icon.py
"""
from __future__ import annotations

import subprocess
import tempfile
import time
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


def banner() -> str:
    """Profile banner, 1360x480 (2x Discord's 680x240). Discord puts the avatar over the bottom-left
    corner, so that corner only gets hills; the words sit up top and the castle bottom-right."""
    w, h = 1360, 480
    stars = "".join(f'<circle cx="{(i * 397) % w}" cy="{(i * 151) % 300 + 12}" r="{1.5 + (i % 3)}" '
                    f'fill="{CREAM}" opacity="{0.35 + (i % 4) * 0.15:.2f}"/>' for i in range(1, 46))
    hills_back = f'<path d="M0 {h} V400 Q180 350 380 392 T760 380 T1100 400 T{w} 385 V{h} Z" fill="{SHADOW}"/>'
    # the castle stands on the far ridge; the near hill covers its footing
    hills_front = f'<path d="M0 {h} V440 Q240 415 520 442 T1000 440 Q1180 430 {w} 445 V{h} Z" fill="{NAVY}"/>'
    moon = (f'<mask id="bite"><rect width="{w}" height="{h}" fill="#fff"/><circle cx="1262" cy="84" r="50" fill="#000"/></mask>'
            f'<circle cx="1240" cy="100" r="54" fill="{CREAM}" mask="url(#bite)"/>')
    serif = 'font-family="Cinzel, Georgia, serif" text-anchor="middle"'
    words = (f'<text x="660" y="112" {serif} font-weight="700" font-size="44" letter-spacing="22" fill="{GOLD}">CASTLE</text>'
             f'<text x="660" y="210" {serif} font-weight="700" font-size="92" letter-spacing="4" fill="{CREAM}">QUARTERMASTER</text>'
             f'<line x1="390" y1="240" x2="930" y2="240" stroke="{GOLD}" stroke-width="3" opacity=".7"/>'
             f'<text x="660" y="290" {serif} font-weight="400" font-size="34" letter-spacing="6" fill="{GOLD}">'
             f'Crafting · Gathering · Guild Bank</text>')
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">
<style>@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@400;700&amp;display=block');</style>
<defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
<stop offset="0" stop-color="{SHADOW}"/><stop offset="1" stop-color="{INNER}"/></linearGradient></defs>
<rect width="{w}" height="{h}" fill="url(#sky)"/>
{stars}{moon}{hills_back}
<g transform="translate(1010 170) scale(0.38)">{castle()}</g>
{hills_front}
{words}
</svg>"""


def render(name: str, markup: str, size: tuple[int, int]) -> Path:
    (HERE / f"{name}.svg").write_text(markup, "utf-8")
    out = HERE / f"{name}.png"
    html = HERE / "_render.html"
    html.write_text(f'<html><body style="margin:0;background:#000">{markup}</body></html>', "utf-8")
    out.unlink(missing_ok=True)
    profile = tempfile.mkdtemp(prefix="edge-render-")  # a fresh profile, so a running Edge can't swallow the job
    subprocess.run([EDGE, "--headless=new", f"--user-data-dir={profile}", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                    f"--window-size={size[0]},{size[1]}", "--virtual-time-budget=5000", f"--screenshot={out}",
                    html.as_uri()], check=True, capture_output=True)
    # msedge.exe hands the job to a background process and returns early, so wait for the file to land
    for _ in range(60):
        if out.exists() and out.stat().st_size > 0:
            break
        time.sleep(0.5)
    else:
        raise SystemExit(f"Edge didn't write {out}")
    time.sleep(0.5)
    html.unlink()
    return out


def main() -> None:
    print(render("icon", svg(), (1024, 1024)))
    print(render("banner", banner(), (1360, 480)))


if __name__ == "__main__":
    main()
