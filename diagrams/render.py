"""Regenerate both SVGs and WebPs from the checked-in scenario traces.

Requires Inkscape on PATH and Pillow for WebP encoding. Neither is needed
to run the project.
"""
import json
from html import escape
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from handshake import trace


def render(source, slug, title, summary):
    rows = list(trace(json.loads((ROOT / "examples" / source).read_text())))
    w, h = 960, 136 + 57 * len(rows)
    label = {"buffered": "Buffered", "waiting": "Waiting", "accepted": "Accepted",
             "applied": "Applied", "unknown": "Unknown", "duplicate": "Duplicate"}
    tone = {"applied": ("#d6f1e5", "#104b38"), "unknown": ("#ffe9cc", "#68411c"),
            "duplicate": ("#e9e4ff", "#463673")}
    text = lambda x, y, s, size=23, color="#142e45": (
        f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}">{escape(str(s))}</text>')
    rect = lambda x,y,rw,rh,fill,rx=0: f'<rect x="{x}" y="{y}" width="{rw}" height="{rh}" fill="{fill}" rx="{rx}"/>'
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img">',
             f'<title>{escape(title)}</title><desc>{escape(summary)}</desc>',
             '<g font-family="DejaVu Sans,sans-serif">',
             rect(0,0,w,h,"#e9f1f5",20), rect(16,16,w-32,88,"#132b42",14),
             text(34,55,title,32,"#ffffff"), text(34,85,summary,20,"#d1e5ef"),
             text(42,127,"STEP",18), text(148,127,"EVENT",18), text(354,127,"RESULT",18),
             text(593,127,"RECIPE",18), text(744,127,"APPLIES",18)]
    for n, op, result, epoch, recipe, count in rows:
        y = 136 + (n-1)*57
        bg, fg = tone.get(result, ("#dfeaf2","#142e45"))
        parts.extend([rect(16,y,w-32,49,"#ffffff" if n%2 else "#f5f9fb",10),
                      text(45,y+33,n), text(148,y+33,op),
                      rect(342,y+6,178,37,bg,8),text(354,y+33,label[result],23,fg),
                      text(594,y+33,recipe),text(748,y+33,count)])
    parts.append("</g></svg>")
    svg = HERE / f"{slug}.svg"
    svg.write_text("\n".join(parts)+"\n", encoding="utf-8")
    with TemporaryDirectory() as td:
        png = Path(td) / "render.png"
        subprocess.run(["inkscape", str(svg), f"--export-filename={png}"],check=True)
        with Image.open(png) as image:
            assert image.size == (w,h)
            image.convert("RGB").save(HERE / f"{slug}.webp", format="WEBP", lossless=True, method=6)


if __name__ == "__main__":
    render("normal.json","plc-hmi-normal-trace","A write, a receipt, then an applied result",
           "Simulated recipe selection · normal.json")
    render("lost-reply.json","plc-hmi-lost-reply-trace","Same request, one application",
           "An expired read does not undo the PLC change · lost-reply.json")
