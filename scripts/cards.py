#!/usr/bin/env python3
"""Render the profile README as a stack of animated SVG cards.

    python scripts/cards.py fetch      refresh data/github.json (needs GITHUB_TOKEN)
    python scripts/cards.py            render every card into cards/
    STATIC=1 python scripts/cards.py   render the final frame into preview/ (for screenshots)

The cards are shown through <img> tags, so each SVG is self-contained: an inline
<style> with CSS keyframes, a few SMIL <animate> loops, and fonts subset with
pyftsubset and embedded as base64 WOFF data URIs. Every animation is switched
off under prefers-reduced-motion; elements rest in their final state.
"""
from __future__ import annotations

import base64
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "github.json"
STATIC = os.environ.get("STATIC", "") not in ("", "0", "false")
OUT = ROOT / ("preview" if STATIC else "cards")

# ── profile ──────────────────────────────────────────────────────────────────
USER = "mariobeltrao"
NAME = "Mário Beltrão"
KICKER = "JOÃO PESSOA · PB"
TAGLINE = "Engenharia de IA e Python, evoluindo todos os dias"
CHIPS = ["Python", "IA · LLMs · RAG", "Web"]
# Hero portrait: drop your art in assets/ as portrait-art.txt (ASCII art, shown as
# text), or an image: .webp/.png (shown in a circle, transparency kept), .svg or .jpg.
# Without it the hero shows MONOGRAM.
PORTRAIT_ART = [ROOT / "assets" / f"portrait-art.{ext}" for ext in ("txt", "webp", "png", "svg", "jpg")]
MONOGRAM = "MB"

# The monthly chart and its stats start here (and show at most the last 12 months).
CHART_FROM = date(2026, 8, 1)

TILES = [
    # slug, title, subtitle ({repos} is filled from the data), icon
    ("projetos", "Projetos", "{repos} repositórios públicos", "code"),
    ("certificados", "Certificados", "{certs} cursos · IA e Python", "medal"),
    ("contato", "Contato", "vamos conversar por e-mail", "mail"),
]

# "O que estou estudando": the AI-engineering path (name, two short lines) and three pillars.
ROADMAP_TAG = "ENGENHARIA DE IA · 2027"
ROADMAP = [
    ("Fundamentos", "machine learning", "estatística · álgebra"),
    ("Deep learning", "redes neurais", ""),
    ("LLMs", "prompt e APIs", "de modelos"),
    ("RAG", "embeddings", "bancos vetoriais"),
    ("Agentes de IA", "uso de", "ferramentas"),
    ("MLOps", "avaliação", "e deploy"),
]
PILLARS = [
    ("Python", "desenvolvimento de aplicações", "prompt"),
    ("Lógica", "resolução de problemas", "bulb"),
    ("Git e GitHub", "versionamento e colaboração", "git"),
]
STUDIES_NOTE = "Cada projeto aqui representa uma etapa da minha evolução como desenvolvedor."

# Featured repos, in order, with the short description shown on the card
# (GitHub's own description is used when this is empty).
FEATURED = [
    ("PyCore", "Jornada estruturada em Python com entregas diárias: fundamentos, lógica, "
               "dados e projetos práticos."),
    ("MasterFit", "Site da rede de academias MasterFit, na Paraíba: hero interativa, zoom por "
                  "satélite, planos e WhatsApp."),
    ("TaskFlow", "Sistema acadêmico em Python para organizar tarefas, provas e prazos."),
    ("MinhaVez", "Simulação em Java de um rodízio veicular inteligente: mobilidade urbana e "
                 "fluxo de veículos."),
]
# Each project card: its step on the green ladder and its illustration.
REPO_LOOK = {"PyCore": (5, "editor"), "MasterFit": (1, "pulse"), "TaskFlow": (2, "checklist"),
             "MinhaVez": (4, "road")}

# Certificates, oldest first: each gets a small linked badge, darker as the path goes on.
# slug, title (short), issuer, date, link
CERTS = [
    ("samsung-agentes-ia", "Fundamentos de Agentes de IA em Python", "Samsung Ocean", date(2026, 8, 13),
     "certificados/samsung-ocean-fundamentos-agentes-ia.pdf"),
    ("python-fundamentals", "Python Programming Fundamentals", "Microsoft · Coursera", date(2026, 8, 21),
     "https://coursera.org/verify/SO5I2YWY5F3T"),
    ("data-analysis", "Data Analysis and Visualization with Python", "Microsoft · Coursera", date(2026, 8, 21),
     "https://coursera.org/verify/06F46MR6VHG6"),
    ("automation", "Automation and Scripting with Python", "Microsoft · Coursera", date(2026, 8, 22),
     "https://coursera.org/verify/0K4MF6KSR9KJ"),
    ("advanced-python", "Advanced Python Development Techniques", "Microsoft · Coursera", date(2026, 8, 24),
     "https://coursera.org/verify/KLBWTBWCT8S4"),
    ("web-development", "Web Development with Python", "Microsoft · Coursera", date(2026, 8, 24),
     "https://coursera.org/verify/IC83356C7ST1"),
    ("project-development", "Project Development in Python", "Microsoft · Coursera", date(2026, 8, 24),
     "https://coursera.org/verify/MG00VK3LWK86"),
    ("dascia-fundamentos-ia", "Fundamentos da IA", "DascIA Academy", date(2026, 11, 11),
     "certificados/dascia-fundamentos-ia.png"),
]

# ── brand: light green (Quicksand + JetBrains Mono) ─────────────────────────
BG = "#D5E8BF"      # card background: light green
PANEL = "#C6DEAB"   # chips, tiles, quiet fills
BORDER = "#ADCB8C"  # frames and rules
OLIVE = "#5E8F2E"   # main accent (bars, underline)
SAGE = "#3F6B1F"    # secondary text, icons, highlighted bar
LEAF = "#2C4320"    # body text
TEXT = "#13200B"    # titles
DIM = "#587046"     # captions
SNAKE = "#1E3A0F"   # the contribution snake
LADDER = ["#C3DEA4", "#9DC871", "#77AD46", "#53892A", "#366A1A", "#22460E"]  # light → dark
ON_DARK, ON_DARK_DIM = "#EEF6E4", "#C3DCA8"
HEAT = ["#C0D9A3", "#9CC56E", "#78AA45", "#53892A", "#2E5B16"]

FONTS = {  # key: (file, weight, css family)
    "q5": ("Quicksand.ttf", 500, "Q"),
    "q7": ("Quicksand.ttf", 700, "Q"),
    "m4": ("JetBrainsMono.ttf", 400, "M"),
    "m6": ("JetBrainsMono.ttf", 600, "M"),
}
FALLBACK = {"Q": "Quicksand,ui-rounded,system-ui,sans-serif",
            "M": "'JetBrains Mono',ui-monospace,Menlo,Consolas,monospace"}

MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
W = 900  # width of full-row cards; README shows them at width 100%


# ── data ─────────────────────────────────────────────────────────────────────
def fetch() -> None:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        sys.exit("fetch needs GITHUB_TOKEN (or GH_TOKEN) in the environment")
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=364)).replace(hour=0, minute=0, second=0, microsecond=0)
    repos = "\n".join(f"r{i}: repository(owner: $login, name: {json.dumps(n)}) {{ ...R }}"
                      for i, (n, _) in enumerate(FEATURED))
    query = f"""
    query($login: String!, $from: DateTime!, $to: DateTime!) {{
      user(login: $login) {{
        name login
        repositories(privacy: PUBLIC, ownerAffiliations: OWNER, isFork: false) {{ totalCount }}
        contributionsCollection(from: $from, to: $to) {{
          contributionCalendar {{ totalContributions
            weeks {{ contributionDays {{ date contributionCount }} }} }}
        }}
      }}
      {repos}
    }}
    fragment R on Repository {{
      name url description stargazerCount forkCount pushedAt primaryLanguage {{ name color }}
    }}"""
    body = json.dumps({"query": query, "variables": {
        "login": USER, "from": start.isoformat(), "to": now.isoformat()}}).encode()
    req = urllib.request.Request("https://api.github.com/graphql", data=body, headers={
        "Authorization": f"bearer {token}", "Content-Type": "application/json",
        "User-Agent": "profile-cards"})
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.load(r)
    if res.get("errors"):
        sys.exit(f"GraphQL errors: {res['errors']}")
    d = res["data"]
    cal = d["user"]["contributionsCollection"]["contributionCalendar"]
    days = [[c["date"], c["contributionCount"]] for w in cal["weeks"] for c in w["contributionDays"]]
    out = {
        "generated_at": now.isoformat(timespec="seconds"),
        "user": {"login": d["user"]["login"], "name": d["user"]["name"],
                 "public_repos": d["user"]["repositories"]["totalCount"]},
        "total": cal["totalContributions"],
        "days": days,
        "repos": {},
    }
    for i, (name, _) in enumerate(FEATURED):
        r = d.get(f"r{i}")
        if r:
            out["repos"][name] = {
                "url": r["url"], "description": r["description"] or "",
                "stars": r["stargazerCount"], "forks": r["forkCount"], "pushed_at": r["pushedAt"],
                "language": (r["primaryLanguage"] or {}).get("name", ""),
            }
    DATA.parent.mkdir(exist_ok=True)
    text = json.dumps(out, ensure_ascii=False, indent=1)
    text = re.sub(r'\[\n\s+("\d{4}-\d\d-\d\d"),\n\s+(\d+)\n\s+\]', r"[\1, \2]", text)  # one day per line
    DATA.write_text(text + "\n")
    print(f"wrote {DATA.relative_to(ROOT)}: {len(days)} days, {out['total']} contributions")


def load() -> dict:
    if not DATA.exists():
        sys.exit(f"{DATA.relative_to(ROOT)} not found; run: GITHUB_TOKEN=... python scripts/cards.py fetch")
    return json.loads(DATA.read_text())


def stats(days: list[tuple[date, int]]) -> dict:
    counts = [c for _, c in days]
    # current streak: today may still be empty, so start from yesterday in that case
    i = len(days) - 1
    if i >= 0 and counts[i] == 0:
        i -= 1
    current = 0
    while i >= 0 and counts[i] > 0:
        current += 1
        i -= 1
    longest = run = 0
    for c in counts:
        run = run + 1 if c else 0
        longest = max(longest, run)
    busiest = max(days, key=lambda d: d[1]) if days else (date.today(), 0)
    end = days[-1][0] if days else date.today()
    first = days[0][0] if days else end
    months = []
    y, m = end.year, end.month
    while len(months) < 12 and (y, m) >= (first.year, first.month):
        months.append((y, m))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    months.reverse()
    per = defaultdict(int)
    for d, c in days:
        per[(d.year, d.month)] += c
    return {"current": current, "longest": longest, "active": sum(1 for c in counts if c),
            "span": len(days), "busiest": busiest, "total": sum(counts),
            "months": [(ym, per[ym]) for ym in months]}


# ── fonts ────────────────────────────────────────────────────────────────────
class Fonts:
    """Static instances of the variable fonts, for measuring and subsetting."""

    def __init__(self) -> None:
        from fontTools.ttLib import TTFont
        from fontTools.varLib import instancer
        self.tmp = Path(tempfile.mkdtemp(prefix="cards-"))
        self.files, self.metrics = {}, {}
        for key, (file, wght, _) in FONTS.items():
            font = TTFont(ROOT / "fonts" / file)
            inst = instancer.instantiateVariableFont(font, {"wght": wght})
            path = self.tmp / f"{key}.ttf"
            inst.save(path)
            cmap, hmtx = inst.getBestCmap(), inst["hmtx"].metrics
            self.files[key] = path
            self.metrics[key] = (cmap, hmtx, inst["head"].unitsPerEm)
        self.tool = ([shutil.which("pyftsubset")] if shutil.which("pyftsubset")
                     else [sys.executable, "-m", "fontTools.subset"])

    def width(self, key: str, text: str, size: float, spacing: float = 0) -> float:
        cmap, hmtx, upm = self.metrics[key]
        units = sum(hmtx[cmap.get(ord(ch), ".notdef")][0] for ch in text)
        return units * size / upm + spacing * len(text)

    def woff(self, key: str, chars: set[str]) -> str:
        txt = self.tmp / f"{key}.txt"
        out = self.tmp / f"{key}.woff"
        txt.write_text("".join(sorted(chars)) + " ")
        subprocess.run([*self.tool, str(self.files[key]), f"--text-file={txt}",
                        f"--output-file={out}", "--flavor=woff", "--layout-features=kern,liga",
                        "--no-hinting", "--desubroutinize", "--name-IDs=1,2"], check=True)
        return base64.b64encode(out.read_bytes()).decode()

    def close(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


# ── svg helpers ──────────────────────────────────────────────────────────────
CSS_MOTION = """
.a{animation-duration:.8s;animation-timing-function:cubic-bezier(.2,.75,.25,1);animation-fill-mode:both}
.rise{animation-name:rise}@keyframes rise{from{opacity:0;transform:translateY(14px)}}
.fade{animation-name:fade}@keyframes fade{from{opacity:0}}
.slide{animation-name:slide}@keyframes slide{from{opacity:0;transform:translateX(-12px)}}
.grow{animation-name:grow;transform-box:fill-box;transform-origin:50% 100%}@keyframes grow{from{transform:scaleY(0)}}
.sweep{animation-name:sweep;transform-box:fill-box;transform-origin:0 50%}@keyframes sweep{from{transform:scaleX(0)}}
.pop{animation-name:pop;animation-duration:.5s;transform-box:fill-box;transform-origin:50% 50%}@keyframes pop{from{opacity:0;transform:scale(.3)}}
.shine{animation-name:shine;animation-duration:1.5s;animation-timing-function:ease-in-out}@keyframes shine{from{transform:translateX(0)}to{transform:translateX(520px)}}
.draw{stroke-dasharray:1;animation-name:draw;animation-duration:1.4s}@keyframes draw{from{stroke-dashoffset:1}}
.still{display:none}
@media (prefers-reduced-motion:reduce){.a{animation:none!important}.motion{display:none}.still{display:inline}/*reduced*/}
"""
CSS_STATIC = ".motion{display:none}"


class Card:
    def __init__(self, fonts: Fonts, name: str, w: int, h: int, start: float, label: str):
        self.fonts, self.name, self.w, self.h, self.t0, self.label = fonts, name, w, h, start, label
        self.parts: list[str] = []
        self.defs: list[str] = []
        self.chars: dict[str, set[str]] = defaultdict(set)
        self.reduced = ""  # extra CSS that applies under prefers-reduced-motion (and STATIC)

    def anim(self, kind: str, at: float) -> str:
        """class/style attributes for a CSS entrance that starts `at` seconds into this card."""
        if STATIC:
            return ""
        return f' class="a {kind}" style="animation-delay:{self.t0 + at:.2f}s"'

    def add(self, s: str) -> None:
        self.parts.append(s)

    def motion(self, animated: str, still: str = "") -> None:
        """SMIL loops go in .motion (hidden under reduced motion); `still` replaces them."""
        if not STATIC:
            self.add(f'<g class="motion">{animated}</g>')
            if still:
                self.add(f'<g class="still">{still}</g>')
        elif still:
            self.add(still)

    def text(self, x: float, y: float, s: str, f: str = "q7", size: float = 16, fill: str = TEXT,
             anchor: str = "start", ls: float = 0, attrs: str = "") -> str:
        self.chars[f].update(s)
        fam = FONTS[f][2]
        extra = f' letter-spacing="{ls}"' if ls else ""
        if anchor != "start":
            extra += f' text-anchor="{anchor}"'
        return (f'<text x="{x:.1f}" y="{y:.1f}" class="{f}" font-size="{size}" fill="{fill}"'
                f'{extra}{attrs}>{escape(s)}</text>')

    def width(self, f: str, s: str, size: float, ls: float = 0) -> float:
        return self.fonts.width(f, s, size, ls)

    def frame(self, radius: int = 18) -> None:
        self.add(f'<rect x=".75" y=".75" width="{self.w - 1.5}" height="{self.h - 1.5}" rx="{radius}" '
                 f'fill="{BG}" stroke="{BORDER}" stroke-width="1.5"/>')

    def svg(self) -> str:
        faces, classes = [], []
        for key, chars in self.chars.items():
            _, wght, fam = FONTS[key]
            data = self.fonts.woff(key, chars)
            faces.append(f'@font-face{{font-family:{fam};font-weight:{wght};'
                         f'src:url(data:font/woff;base64,{data}) format("woff")}}')
            classes.append(f'.{key}{{font-family:{fam},{FALLBACK[fam]};font-weight:{wght}}}')
        css = "".join(faces) + "".join(classes) + (CSS_STATIC + self.reduced if STATIC else CSS_MOTION.replace("/*reduced*/", self.reduced))
        defs = f"<defs>{''.join(self.defs)}</defs>" if self.defs else ""
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
                f'viewBox="0 0 {self.w} {self.h}" role="img" aria-label="{escape(self.label)}">'
                f"<title>{escape(self.label)}</title><style>{css}</style>{defs}"
                + "".join(self.parts) + "</svg>\n")

    def save(self) -> None:
        path = OUT / f"{self.name}.svg"
        path.write_text(self.svg())
        print(f"  {path.relative_to(ROOT)}  {path.stat().st_size / 1024:.1f} KB")


def num(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def fmt_day(d: date) -> str:
    return f"{d.day} {MONTHS[d.month - 1]}"


def wrap(card: Card, text: str, f: str, size: float, width: float, lines: int) -> list[str]:
    words, out, cur = text.split(), [], ""
    for w in words:
        nxt = f"{cur} {w}".strip()
        if card.width(f, nxt, size) <= width:
            cur = nxt
        else:
            out.append(cur)
            cur = w
    out.append(cur)
    if len(out) > lines:
        out = out[:lines]
        last = out[-1]
        while card.width(f, last + "…", size) > width and " " in last:
            last = last.rsplit(" ", 1)[0]
        out[-1] = last.rstrip(",.:;") + "…"
    return out


ICONS = {  # 24×24 stroke icons
    "code": ['<path d="M8 6 2.5 12 8 18M16 6l5.5 6-5.5 6M13.5 4l-3 16"/>'],
    "medal": ['<circle cx="12" cy="9" r="6"/>', '<path d="M8.6 14 7 22l5-3 5 3-1.6-8"/>'],
    "prompt": ['<rect x="2.5" y="4" width="19" height="16" rx="3"/>', '<path d="m7 10 3 2.5L7 15M12.5 15.5H17"/>'],
    "bulb": ['<path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.6 10.8c.7.5 1.1 1.3 1.1 2.1V16h5v-.1c0-.8.4-1.6 1.1-2.1A6 6 0 0 0 12 3z"/>'],
    "git": ['<circle cx="6" cy="5" r="2.2"/>', '<circle cx="6" cy="19" r="2.2"/>', '<circle cx="18" cy="7" r="2.2"/>',
            '<path d="M6 7.2v9.6M18 9.2c0 5-12 2.8-12 7.6"/>'],
    "flame": ['<path d="M12 2.5c.8 3.6 4.8 5.3 4.8 10a4.8 4.8 0 0 1-9.6 0c0-2.4 1.3-3.6 2.4-5 .4 1.9 1.4 2.8 2.4 2.8 0-2.8-.9-4.6 0-7.8z"/>'],
    "calendar": ['<rect x="3" y="5" width="18" height="16" rx="3"/>', '<path d="M3 10h18M8 3v4M16 3v4"/>'],
    "bolt": ['<path d="M13 2.5 4.5 14H11l-1 7.5L19.5 10H13z"/>'],
    "mail": ['<rect x="2.5" y="5" width="19" height="14" rx="2.5"/>', '<path d="m3 7 9 6.5L21 7"/>'],
}


# ── cards ────────────────────────────────────────────────────────────────────
def hero(fonts: Fonts, start: float) -> None:
    H = 320
    c = Card(fonts, "hero", W, H, start, f"{NAME}: {TAGLINE}")
    c.defs.append(f'<radialGradient id="glow" cx="80%" cy="50%" r="45%">'
                  f'<stop offset="0" stop-color="{OLIVE}" stop-opacity=".16"/>'
                  f'<stop offset="1" stop-color="{OLIVE}" stop-opacity="0"/></radialGradient>')
    c.frame()
    c.add(f'<rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="17" fill="url(#glow)"{c.anim("fade", .2)}/>')

    c.add(f'<g{c.anim("slide", .1)}><rect x="52" y="77" width="8" height="8" rx="2" fill="{OLIVE}"/>'
          + c.text(70, 85, KICKER, "m6", 12, SAGE, ls=2.4) + "</g>")
    size = 60
    while c.width("q7", NAME, size) > 500:
        size -= 2
    c.add(f'<g{c.anim("rise", .25)}>' + c.text(48, 158, NAME, "q7", size) + "</g>")
    c.add(f'<rect x="52" y="178" width="72" height="4" rx="2" fill="{OLIVE}"{c.anim("sweep", .6)}/>')

    tsize = 21
    while c.width("q5", TAGLINE, tsize) > 500:
        tsize -= 1
    c.add(f'<g{c.anim("rise", .5)}>' + c.text(52, 222, TAGLINE, "q5", tsize, LEAF) + "</g>")
    cx = 52 + c.width("q5", TAGLINE, tsize) + 6
    cursor = f'<rect x="{cx:.1f}" y="{222 - tsize * .78:.1f}" width="2.5" height="{tsize * .95:.1f}" fill="{OLIVE}"'
    c.motion(f'{cursor} opacity="0"><animate attributeName="opacity" values="1;1;0;0" '
             f'keyTimes="0;.5;.5;1" dur="1.1s" begin="{start + 1.1:.2f}s" repeatCount="indefinite"/></rect>',
             f"{cursor}/>")

    x = 52
    for i, chip in enumerate(CHIPS):
        w = c.width("m4", chip, 12) + 26
        c.add(f'<g{c.anim("pop", .8 + i * .12)}><rect x="{x:.1f}" y="248" width="{w:.1f}" height="28" rx="14" '
              f'fill="{PANEL}" stroke="{BORDER}"/>' + c.text(x + w / 2, 266.5, chip, "m4", 12, SAGE, "middle")
              + "</g>")
        x += w + 10

    art = next((p for p in PORTRAIT_ART if p.exists()), None)
    bx, by, bw, bh = 580, 14, 290, H - 28  # box the art is fitted into (right side)
    if art and art.suffix == ".txt":
        rows = art.read_text().rstrip("\n").split("\n")
        cols = max(len(r) for r in rows)
        ratio = c.width("m6", "@", 1)  # character width per font-size unit
        fs = min(bw / (cols * ratio), bh / (len(rows) * 1.12))
        lh = fs * 1.12
        ax = bx + bw - cols * ratio * fs
        ay = by + (bh - lh * len(rows)) / 2
        lines = [f'<g{c.anim("fade", .3 + i * min(.02, 1.2 / len(rows)))}>' + c.text(
                     ax, ay + lh * (i + .8), row, "m6", round(fs, 2), TEXT, attrs=' xml:space="preserve"') + "</g>"
                 for i, row in enumerate(rows) if row.strip()]
        c.add(f'<g style="white-space:pre">{"".join(lines)}</g>')
    elif art:
        mime = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
                ".webp": "image/webp"}[art.suffix]
        data = base64.b64encode(art.read_bytes()).decode()
        px, py, r = 742, H / 2, 128
        # ring that draws itself, a slow dotted orbit, then the portrait pops in
        c.add(f'<circle cx="{px}" cy="{py}" r="{r + 9}" fill="none" stroke="{OLIVE}" stroke-width="2.5" '
              f'pathLength="1" transform="rotate(-90 {px} {py})"{c.anim("draw", .3)}/>')
        orbit = (f'<circle cx="{px}" cy="{py}" r="{r + 19}" fill="none" stroke="{SAGE}" stroke-opacity=".45" '
                 f'stroke-width="1.6" stroke-dasharray="1.5 9" stroke-linecap="round"')
        c.motion(f'{orbit}><animateTransform attributeName="transform" type="rotate" '
                 f'from="0 {px} {py}" to="360 {px} {py}" dur="60s" repeatCount="indefinite"/></circle>',
                 f"{orbit}/>")
        c.defs.append(f'<clipPath id="face"><circle cx="{px}" cy="{py}" r="{r}"/></clipPath>')
        c.add(f'<g{c.anim("pop", .45)}><image href="data:{mime};base64,{data}" x="{px - r}" y="{py - r}" '
              f'width="{2 * r}" height="{2 * r}" preserveAspectRatio="xMidYMid slice" clip-path="url(#face)"/></g>')
    else:
        px, py, r = 752, H / 2, 92
        c.add(f'<g{c.anim("pop", .45)}><circle cx="{px}" cy="{py}" r="{r}" fill="{PANEL}" stroke="{BORDER}"/>'
              + c.text(px, py + 22, MONOGRAM, "q7", 62, SAGE, "middle") + "</g>")
    c.save()


def on(bg_index: int) -> tuple[str, str]:
    """(text, secondary) colours that read on LADDER[bg_index]."""
    return (ON_DARK, ON_DARK_DIM) if bg_index >= 3 else (TEXT, LEAF)


def icon(name: str, x: float, y: float, scale: float, color: str, card: Card, at: float, width: float = 1.6) -> str:
    return (f'<g transform="translate({x:.1f} {y:.1f}) scale({scale})" fill="none" stroke="{color}" '
            f'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round">'
            + "".join(p.replace("/>", f' pathLength="1"{card.anim("draw", at)}/>') for p in ICONS[name]) + "</g>")


def tile(fonts: Fonts, step: int, slug: str, title: str, sub: str, ico: str, start: float) -> None:
    """The three tiles form a light → dark ladder of greens."""
    k = (0, 2, 4)[step]
    bg = LADDER[k]
    fg, fg2 = on(k)
    c = Card(fonts, f"tile-{slug}", 290, 150, start, f"{title}: {sub}")
    c.defs.append(f'<clipPath id="r"><rect width="290" height="150" rx="16"/></clipPath>')
    c.add(f'<rect x=".75" y=".75" width="288.5" height="148.5" rx="16" fill="{bg}" stroke="{fg}" stroke-opacity=".12"/>')
    # oversized faded icon for depth
    c.add(f'<g clip-path="url(#r)" opacity=".1"{c.anim("fade", .3)}>' +
          icon(ico, 178, 52, 5.2, fg, c, .3, 1.4).replace(' class="a draw"', ' class="a fade"') + "</g>")
    c.add(icon(ico, 24, 24, 1.25, fg, c, .1))
    c.add(f'<g{c.anim("slide", .35)}><circle cx="252" cy="38" r="16" fill="{fg}" fill-opacity=".1"/>'
          + c.text(252, 44, "→", "m4", 17, fg, "middle") + "</g>")
    c.add(f'<g{c.anim("rise", .2)}>' + c.text(24, 102, title, "q7", 25, fg) + "</g>")
    c.add(f'<g{c.anim("rise", .3)}>' + c.text(24, 126, sub, "m4", 11.5, fg2) + "</g>")
    c.save()


def studies(fonts: Fonts, start: float) -> None:
    H = 356
    c = Card(fonts, "studies", W, H, start, "O que estou estudando: " + ", ".join(r[0] for r in ROADMAP)
             + "; " + ", ".join(p[0] for p in PILLARS))
    c.defs.append(f'<linearGradient id="track" x1="0" x2="1"><stop offset="0" stop-color="{LADDER[1]}"/>'
                  f'<stop offset="1" stop-color="{LADDER[5]}"/></linearGradient>')
    c.frame()
    c.add(f'<g{c.anim("rise", 0)}>' + c.text(40, 54, "O que estou estudando", "q7", 22) + "</g>")
    tag = ROADMAP_TAG
    tw = c.width("m6", tag, 10.5, 1.2) + 26
    c.add(f'<g{c.anim("pop", .2)}><rect x="{860 - tw:.1f}" y="36" width="{tw:.1f}" height="26" rx="13" fill="{PANEL}"/>'
          + c.text(860 - tw / 2, 53, tag, "m6", 10.5, SAGE, "middle", ls=1.2) + "</g>")

    n = len(ROADMAP)
    x0, x1, ty = 100, 800, 118
    step = (x1 - x0) / (n - 1)
    c.add(f'<line x1="{x0}" x2="{x1}" y1="{ty}" y2="{ty}" stroke="{PANEL}" stroke-width="6" stroke-linecap="round"/>')
    c.add(f'<line x1="{x0}" x2="{x1}" y1="{ty}" y2="{ty}" stroke="url(#track)" stroke-width="6" '
          f'stroke-linecap="round"{c.anim("sweep", .3)}/>')
    for k, (name, l1, l2) in enumerate(ROADMAP):
        x = x0 + k * step
        fg, _ = on(k)
        t = .35 + k * .18
        c.add(f'<g{c.anim("pop", t)}><circle cx="{x:.1f}" cy="{ty}" r="22" fill="{LADDER[k]}" stroke="{BG}" '
              f'stroke-width="4"/>' + c.text(x, ty + 5.5, str(k + 1), "q7", 16, fg, "middle") + "</g>")
        c.add(f'<g{c.anim("rise", t + .1)}>' + c.text(x, ty + 50, name, "q7", 15, TEXT, "middle")
              + c.text(x, ty + 68, l1, "m4", 10.5, DIM, "middle")
              + (c.text(x, ty + 83, l2, "m4", 10.5, DIM, "middle") if l2 else "") + "</g>")
    # a soft pulse on the first step: where the path starts
    c.motion(f'<circle cx="{x0}" cy="{ty}" r="22" fill="none" stroke="{LADDER[2]}" stroke-width="2" opacity="0">'
             f'<animate attributeName="r" values="22;34" dur="2.2s" begin="{start + 1.6:.2f}s" repeatCount="indefinite"/>'
             f'<animate attributeName="opacity" values=".8;0" dur="2.2s" begin="{start + 1.6:.2f}s" '
             f'repeatCount="indefinite"/></circle>')

    gap, py, ph = 14, 236, 64
    pw = (820 - 2 * gap) / 3
    for k, (name, sub, ico) in enumerate(PILLARS):
        x = 40 + k * (pw + gap)
        li = (1, 3, 5)[k]
        fg, fg2 = on(li)
        t = 1.4 + k * .15
        c.add(f'<g{c.anim("rise", t)}><rect x="{x:.1f}" y="{py}" width="{pw:.1f}" height="{ph}" rx="14" '
              f'fill="{LADDER[li]}"/><circle cx="{x + 34:.1f}" cy="{py + ph / 2}" r="18" fill="{fg}" fill-opacity=".12"/>'
              + icon(ico, x + 22, py + ph / 2 - 12, 1, fg, c, t + .2)
              + c.text(x + 64, py + 28, name, "q7", 16, fg) + c.text(x + 64, py + 46, sub, "m4", 10.5, fg2) + "</g>")
    c.add(f'<g{c.anim("fade", 2)}>' + c.text(W / 2, 334, STUDIES_NOTE, "q5", 14, LEAF, "middle") + "</g>")
    c.save()


def smooth(pts: list[tuple[float, float]]) -> str:
    """Monotone cubic (Fritsch–Carlson) through the points: smooth, never overshoots a bar top."""
    n = len(pts)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    d = [(ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i]) for i in range(n - 1)]
    m = [d[0]] + [0.0 if d[i - 1] * d[i] <= 0 else (d[i - 1] + d[i]) / 2 for i in range(1, n - 1)] + [d[-1]]
    for i in range(n - 1):
        if d[i] == 0:
            m[i] = m[i + 1] = 0.0
        else:
            a_, b_ = m[i] / d[i], m[i + 1] / d[i]
            if a_ * a_ + b_ * b_ > 9:
                t = 3 / math.hypot(a_, b_)
                m[i], m[i + 1] = t * a_ * d[i], t * b_ * d[i]
    path = f"M{xs[0]:.1f} {ys[0]:.1f}"
    for i in range(n - 1):
        h = (xs[i + 1] - xs[i]) / 3
        path += (f" C{xs[i] + h:.1f} {ys[i] + m[i] * h:.1f} {xs[i + 1] - h:.1f} {ys[i + 1] - m[i + 1] * h:.1f} "
                 f"{xs[i + 1]:.1f} {ys[i + 1]:.1f}")
    return path


def monthly(fonts: Fonts, s: dict, start: float) -> None:
    (fy, fm), n = s["months"][0][0], len(s["months"])
    since = f"{MONTHS[fm - 1]} {fy}"
    H = 330
    c = Card(fonts, "contributions-monthly", W, H, start,
             f"Contribuições por mês: {s['total']} desde {since}, sequência atual de {s['current']} dias")
    c.defs.append(f'<linearGradient id="bar" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{LADDER[2]}"/>'
                  f'<stop offset="1" stop-color="{LADDER[3]}"/></linearGradient>'
                  f'<linearGradient id="best" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{LADDER[4]}"/>'
                  f'<stop offset="1" stop-color="{LADDER[5]}"/></linearGradient>'
                  f'<filter id="glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="9"/></filter>')
    c.frame()
    c.add(f'<g{c.anim("rise", 0)}>' + c.text(40, 54, "Contribuições por mês", "q7", 22) + "</g>")
    c.add(f'<g{c.anim("fade", .15)}>' + c.text(40, 77, f"{num(s['total'])} desde {since} · média "
                                                         f"{s['total'] / n:.0f}/mês", "m4", 12, DIM) + "</g>")

    px0, py0, pw, ph = 28, 96, 572, 208
    c.add(f'<rect x="{px0}" y="{py0}" width="{pw}" height="{ph}" rx="16" fill="{PANEL}" fill-opacity=".55"/>')
    x0, x1, base, top = 52, 580, 270, 138
    peak = max((v for _, v in s["months"]), default=0) or 1
    for f in (1 / 3, 2 / 3, 1):
        gy = base - (base - top) * f
        c.add(f'<line x1="{x0}" x2="{x1}" y1="{gy:.1f}" y2="{gy:.1f}" stroke="{BORDER}" stroke-dasharray="2 6"/>')
    c.add(f'<line x1="{x0}" x2="{x1}" y1="{base + .5}" y2="{base + .5}" stroke="{BORDER}" stroke-width="1.5"/>')

    slot = (x1 - x0) / n
    bw = min(slot * .46, 58)
    best = max(range(n), key=lambda i: s["months"][i][1])
    bm, bv = s["months"][best]
    ptxt = f"pico · {MONTHS[bm[1] - 1]} · {num(bv)}"
    pwid = c.width("m6", ptxt, 10.5) + 24
    c.add(f'<g{c.anim("pop", .9)}><rect x="{600 - 16 - pwid:.1f}" y="{py0 + 14}" width="{pwid:.1f}" height="24" '
          f'rx="12" fill="{LADDER[5]}"/>' + c.text(600 - 16 - pwid / 2, py0 + 30, ptxt, "m6", 10.5, ON_DARK, "middle")
          + "</g>")
    tops = []
    for i, ((y, m), v) in enumerate(s["months"]):
        cx = x0 + slot * i + slot / 2
        h = max((base - top) * v / peak, 3)
        t = .25 + i * .09
        tops.append((cx, base - h))
        if i == best and v:
            c.add(f'<rect x="{cx - bw / 2:.1f}" y="{base - h:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="10" '
                  f'fill="{LADDER[3]}" opacity=".45" filter="url(#glow)"{c.anim("fade", t + .4)}/>')
        c.add(f'<rect x="{cx - bw / 2:.1f}" y="{base - h:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="10" '
              f'fill="url(#{"best" if i == best and v else "bar"})"{c.anim("grow", t)}/>')
        label = MONTHS[m - 1] if m != 1 or i == 0 else f"{MONTHS[0]} {str(y)[2:]}"
        c.add(c.text(cx, base + 22, label, "m6" if i == best else "m4", 11, TEXT if i == best else DIM, "middle"))
    # curve through the bar tops, then value pills on each point
    if n > 1:
        c.add(f'<path d="{smooth(tops)}" fill="none" stroke="{SNAKE}" stroke-width="2.2" stroke-linecap="round" '
              f'pathLength="1"{c.anim("draw", .8)}/>')
    for i, ((cx, ty), (_, v)) in enumerate(zip(tops, s["months"])):
        t = 1 + i * .1
        txt = num(v)
        w = c.width("m6", txt, 10.5) + 14
        dark = i == best
        c.add(f'<g{c.anim("pop", t)}><circle cx="{cx:.1f}" cy="{ty:.1f}" r="4.5" fill="{BG}" stroke="{SNAKE}" '
              f'stroke-width="2"/><rect x="{cx - w / 2:.1f}" y="{ty - 32:.1f}" width="{w:.1f}" height="19" rx="9.5" '
              f'fill="{SNAKE if dark else BG}"/>'
              + c.text(cx, ty - 18.5, txt, "m6", 10.5, ON_DARK if dark else SAGE, "middle") + "</g>")

    # stat tiles: light → dark ladder
    bd, bc = s["busiest"]
    pct = s["active"] / max(s["span"], 1)
    rows = [
        ("flame", "SEQUÊNCIA ATUAL", str(s["current"]), "dia" if s["current"] == 1 else "dias", f"recorde: {s['longest']}"),
        ("calendar", "DIAS ATIVOS", str(s["active"]), f"de {s['span']}", f"desde {since}"),
        ("bolt", "DIA MAIS INTENSO", str(bc), "contribuições" if bc != 1 else "contribuição", f"em {fmt_day(bd)} {bd.year}"),
    ]
    sx, sw, sh = 618, 254, 82
    for k, (ico, label, value, unit, note) in enumerate(rows):
        y = 28 + k * (sh + 10)
        li = (0, 2, 4)[k]
        fg, fg2 = on(li)
        t = .5 + k * .15
        vw = c.width("q7", value, 26)
        g = (f'<rect x="{sx}" y="{y}" width="{sw}" height="{sh}" rx="16" fill="{LADDER[li]}"/>'
             f'<circle cx="{sx + 32}" cy="{y + sh / 2}" r="19" fill="{fg}" fill-opacity=".12"/>'
             + icon(ico, sx + 20, y + sh / 2 - 12, 1, fg, c, t + .2, 1.8)
             + c.text(sx + 64, y + 26, label, "m6", 9.5, fg2, ls=1.4)
             + c.text(sx + 63, y + 55, value, "q7", 26, fg)
             + c.text(sx + 69 + vw, y + 55, unit, "q5", 13, fg2)
             + c.text(sx + 64, y + 72, note, "m4", 10, fg2))
        if ico == "calendar":
            rx, ry = sx + sw - 36, y + sh / 2
            g += (f'<circle cx="{rx}" cy="{ry}" r="20" fill="none" stroke="{fg}" stroke-opacity=".15" stroke-width="5"/>'
                  f'<circle cx="{rx}" cy="{ry}" r="20" fill="none" stroke="{LADDER[5]}" stroke-width="5" '
                  f'stroke-linecap="round" pathLength="100" stroke-dasharray="{pct * 100:.1f} 100" '
                  f'transform="rotate(-90 {rx} {ry})"/>'
                  + c.text(rx, ry + 4, f"{pct * 100:.0f}%", "m6", 10.5, fg, "middle"))
        c.add(f'<g{c.anim("rise", t)}>{g}</g>')
        if ico == "flame" and s["current"]:
            fx, fy_ = sx + 32, y + sh / 2
            c.motion(f'<circle cx="{fx}" cy="{fy_}" r="19" fill="none" stroke="{LADDER[3]}" stroke-width="1.5" opacity="0">'
                     f'<animate attributeName="r" values="19;27" dur="1.8s" begin="{start + 1.2:.2f}s" repeatCount="indefinite"/>'
                     f'<animate attributeName="opacity" values=".8;0" dur="1.8s" begin="{start + 1.2:.2f}s" '
                     f'repeatCount="indefinite"/></circle>')
    c.save()


def art(kind: str, c: Card, x: float, y: float, a1: str, a2: str, a3: str, start: float) -> None:
    """Small animated illustration for a project card, in a 130×150 box at (x, y)."""
    g = lambda body, at=0, kind_="fade": c.add(f'<g transform="translate({x} {y})"><g{c.anim(kind_, at)}>{body}</g></g>')
    if kind == "editor":
        g(f'<rect width="130" height="132" rx="12" fill="{a3}" fill-opacity=".14"/>'
          + "".join(f'<circle cx="{14 + i * 11}" cy="14" r="3.5" fill="{a1}" fill-opacity="{.9 - i * .25}"/>' for i in range(3)), .2)
        bars = [(0, 62, a1), (12, 78, a2), (12, 46, a2), (0, 88, a1), (24, 52, a2), (12, 70, a2)]
        for i, (ind, w, col) in enumerate(bars):
            c.add(f'<g transform="translate({x} {y})"><rect x="{14 + ind}" y="{34 + i * 15}" width="{w}" height="7" '
                  f'rx="3.5" fill="{col}"{c.anim("sweep", .4 + i * .12)}/></g>')
        cur = f'<rect x="{x + 14 + 70 + 6}" y="{y + 34 + 5 * 15 - 1}" width="3" height="9" fill="{a1}"'
        c.motion(f'{cur} opacity="0"><animate attributeName="opacity" values="1;1;0;0" keyTimes="0;.5;.5;1" '
                 f'dur="1s" begin="{start + 1.3:.2f}s" repeatCount="indefinite"/></rect>', f"{cur}/>")
    elif kind == "pulse":
        g(f'<rect x="20" y="22" width="12" height="40" rx="4" fill="{a1}"/><rect x="34" y="30" width="8" height="24" rx="3" fill="{a2}"/>'
          f'<rect x="42" y="38" width="46" height="8" rx="4" fill="{a2}"/>'
          f'<rect x="88" y="30" width="8" height="24" rx="3" fill="{a2}"/><rect x="98" y="22" width="12" height="40" rx="4" fill="{a1}"/>',
          .2, "pop")
        beat = "M0 112 H34 L44 92 L54 132 L66 78 L76 120 L84 104 L92 112 H130"
        c.add(f'<g transform="translate({x} {y})"><path d="{beat}" fill="none" stroke="{a2}" stroke-width="2.5" '
              f'stroke-linecap="round" stroke-linejoin="round" pathLength="1"{c.anim("draw", .5)}/></g>')
        c.motion(f'<g transform="translate({x} {y})"><path d="{beat}" fill="none" stroke="{a1}" stroke-width="3.5" '
                 f'stroke-linecap="round" stroke-linejoin="round" pathLength="100" stroke-dasharray="14 186" '
                 f'stroke-dashoffset="14"><animate attributeName="stroke-dashoffset" values="14;-100" dur="1.8s" '
                 f'begin="{start + 1.6:.2f}s" repeatCount="indefinite"/></path></g>')
    elif kind == "checklist":
        for i in range(4):
            yy = 14 + i * 32
            done = i < 3
            c.add(f'<g transform="translate({x} {y})"><g{c.anim("slide", .3 + i * .15)}>'
                  f'<rect x="6" y="{yy}" width="20" height="20" rx="6" fill="{a1 if done else "none"}" '
                  f'stroke="{a1}" stroke-width="2"/>'
                  f'<rect x="38" y="{yy + 6}" width="{[78, 60, 70, 50][i]}" height="8" rx="4" fill="{a2}" '
                  f'fill-opacity="{.45 if done else .9}"/></g>'
                  + (f'<path d="M11 {yy + 10}l4 4 7-8" fill="none" stroke="{a3}" stroke-width="2.5" '
                     f'stroke-linecap="round" stroke-linejoin="round" pathLength="1"{c.anim("draw", .7 + i * .25)}/>'
                     if done else "") + "</g>")
        box = f'<rect x="{x + 6}" y="{y + 14 + 3 * 32}" width="20" height="20" rx="6" fill="none" stroke="{a1}" stroke-width="2"'
        c.motion(f'{box} opacity="0"><animate attributeName="opacity" values="0;1;0" dur="1.6s" '
                 f'begin="{start + 1.8:.2f}s" repeatCount="indefinite"/></rect>')
    elif kind == "road":
        c.defs.append(f'<clipPath id="road"><rect x="{x}" y="{y + 52}" width="130" height="76" rx="12"/></clipPath>')
        g(f'<rect x="0" y="52" width="130" height="76" rx="12" fill="{a3}" fill-opacity=".85"/>'
          f'<rect x="96" y="0" width="26" height="46" rx="8" fill="{a3}" fill-opacity=".85"/>', .2)
        lights = [(9, "#E35D4F"), (23, "#E8C547"), (37, a1)]
        for i, (ly, col) in enumerate(lights):
            dot = f'<circle cx="{x + 109}" cy="{y + ly}" r="5" fill="{col}"'
            vals = ["1;.25;.25", ".25;1;.25", ".25;.25;1"][i]
            c.motion(f'{dot} opacity=".25"><animate attributeName="opacity" values="{vals}" calcMode="discrete" '
                     f'dur="4.5s" begin="{start + 1:.2f}s" repeatCount="indefinite"/></circle>',
                     f'{dot} opacity="{1 if i == 2 else .25}"/>')
        lane = f'<line x1="{x}" x2="{x + 130}" y1="{y + 90}" y2="{y + 90}" stroke="{a2}" stroke-width="2.5" stroke-dasharray="10 9"'
        c.motion(f'{lane}><animate attributeName="stroke-dashoffset" values="0;-38" dur=".9s" repeatCount="indefinite"/></line>',
                 f"{lane}/>")
        def car(cy: float, col: str, dx: str, dur: float, x_still: float) -> None:
            body = (f'<rect x="-17" y="-9" width="34" height="18" rx="6" fill="{col}"/>'
                    f'<rect x="-4" y="-6" width="10" height="12" rx="2.5" fill="{a3}" fill-opacity=".55"/>')
            c.motion(f'<g clip-path="url(#road)"><g transform="translate({x} {y + cy})">{body}'
                     f'<animateTransform attributeName="transform" type="translate" values="{dx}" dur="{dur}s" '
                     f'begin="{start + .8:.2f}s" repeatCount="indefinite"/></g></g>',
                     f'<g transform="translate({x + x_still} {y + cy})">{body}</g>')
        car(71, a1, f"{x - 20} {y + 71};{x + 150} {y + 71}", 3.4, 40)
        car(110, a2, f"{x + 150} {y + 110};{x - 20} {y + 110}", 4.6, 92)


def repo(fonts: Fonts, idx: int, name: str, blurb: str, info: dict, start: float) -> None:
    li, kind = REPO_LOOK.get(name, (2, "editor"))
    bg = LADDER[li]
    fg, fg2 = on(li)
    a1, a2, a3 = ((LADDER[0], LADDER[1], LADDER[2]) if li >= 3 else (LADDER[5], LADDER[4], LADDER[3]))
    desc = blurb or info.get("description", "")
    Wc, Hc = 440, 244
    c = Card(fonts, f"repo-{name.lower()}", Wc, Hc, start, f"{name}: {desc}")
    c.defs.append(f'<clipPath id="clip"><rect width="{Wc}" height="{Hc}" rx="18"/></clipPath>')
    c.add(f'<rect x=".75" y=".75" width="{Wc - 1.5}" height="{Hc - 1.5}" rx="18" fill="{bg}" stroke="{fg}" '
          f'stroke-opacity=".12"/>')
    c.add(f'<g clip-path="url(#clip)"><circle cx="{Wc - 70}" cy="96" r="130" fill="{fg}" fill-opacity=".05"'
          f'{c.anim("pop", .1)}/></g>')

    lang = info.get("language") or ""
    pill = f"{idx:02d}" + (f" · {lang}" if lang else "")
    pw = c.width("m6", pill, 10.5) + 22
    c.add(f'<g{c.anim("slide", .1)}><rect x="24" y="24" width="{pw:.1f}" height="24" rx="12" fill="{fg}" '
          f'fill-opacity=".1"/>' + c.text(24 + pw / 2, 40, pill, "m6", 10.5, fg, "middle") + "</g>")
    c.add(f'<g{c.anim("rise", .15)}>' + c.text(24, 90, name, "q7", 30, fg) + "</g>")
    lines = wrap(c, desc, "q5", 13.5, 248, 4)
    c.add(f'<g{c.anim("rise", .25)}>' + "".join(
        c.text(25, 118 + 19 * j, ln, "q5", 13.5, fg2) for j, ln in enumerate(lines)) + "</g>")

    meta, x, y = [], 25, 218
    if "stars" in info:
        meta.append(f'<path transform="translate({x} {y - 11}) scale(.5)" fill="none" stroke="{fg2}" '
                    f'stroke-width="2.4" stroke-linejoin="round" d="M12 2.5l2.9 6.1 6.6.8-4.9 4.6 1.3 6.6'
                    f'L12 17.3l-5.9 3.3 1.3-6.6-4.9-4.6 6.6-.8z"/>')
        meta.append(c.text(x + 17, y, str(info["stars"]), "m4", 11, fg2))
        x += 17 + c.width("m4", str(info["stars"]), 11) + 18
    if info.get("pushed_at"):
        p = datetime.fromisoformat(info["pushed_at"].replace("Z", "+00:00"))
        meta.append(c.text(x, y, f"atualizado {MONTHS[p.month - 1]} {p.year}", "m4", 11, fg2))
    c.add(f'<g{c.anim("fade", .45)}>{"".join(meta)}</g>')
    cta = "ver projeto →"
    cw = c.width("m6", cta, 11) + 26
    c.add(f'<g{c.anim("slide", .5)}><rect x="{Wc - 24 - cw:.1f}" y="{y - 17}" width="{cw:.1f}" height="26" rx="13" '
          f'fill="{fg}"/>' + c.text(Wc - 24 - cw / 2, y, cta, "m6", 11, bg, "middle") + "</g>")
    art(kind, c, 288, 40, a1, a2, a3, start)
    c.save()


def snake_route(cells: dict[tuple[int, int], int], cols: int) -> list[tuple[int, int]]:
    """Grid points a snake visits: from the left edge, always to the nearest cell with
    contributions (moving along the grid), then out through the right edge."""
    todo = {k for k, v in cells.items() if v}
    pos = (-2, 0)
    pts = [pos]
    while todo:
        nxt = min(todo, key=lambda k: (abs(k[0] - pos[0]) + abs(k[1] - pos[1]), k[0], k[1]))
        if nxt[0] != pos[0] and nxt[1] != pos[1]:
            pts.append((nxt[0], pos[1]))  # horizontal first, then vertical
        pts.append(nxt)
        todo.discard(nxt)
        pos = nxt
    pts.append((cols + 5, pos[1]))
    return pts


def graph(fonts: Fonts, days: list[tuple[date, int]], s: dict, start: float) -> None:
    c = Card(fonts, "contribution-graph", W, 220, start,
             f"Gráfico de contribuições: {s['total']} no último ano, percorrido por uma cobrinha")
    c.frame()
    c.defs.append(f'<clipPath id="inside"><rect x="1" y="1" width="{W - 2}" height="218" rx="17"/></clipPath>')
    first, last = days[0][0], days[-1][0]
    c.add(f'<g{c.anim("rise", 0)}>' + c.text(40, 48, "Gráfico de contribuições", "q7", 20) + "</g>")
    c.add(f'<g{c.anim("fade", .1)}>' + c.text(
        860, 48, f"{num(s['total'])} contribuições · {MONTHS[first.month - 1]} {first.year} – "
                 f"{MONTHS[last.month - 1]} {last.year}", "m4", 11.5, DIM, "end") + "</g>")

    pitch, cell = 14.6, 11.6
    off = (first.weekday() + 1) % 7  # weeks start on Sunday, like GitHub
    cols = (len(days) + off + 6) // 7
    gx = 860 - (cols * pitch - (pitch - cell))
    gy = 80
    for row, lab in ((1, "seg"), (3, "qua"), (5, "sex")):
        c.add(c.text(gx - 10, gy + row * pitch + cell - 2, lab, "m4", 9.5, DIM, "end"))
    peak = max((v for _, v in days), default=0) or 1
    level = {}
    seen = None
    for i, (d, v) in enumerate(days):
        col, row = divmod(i + off, 7)
        level[(col, row)] = 0 if v == 0 else min(4, math.ceil(4 * v / peak))
        if d.day <= 7 and row == 0 and d.month != seen and col < cols - 2:
            seen = d.month
            c.add(c.text(gx + col * pitch, gy - 9, MONTHS[d.month - 1], "m4", 9.5, DIM))

    # the snake: a thick dash sliding along the route (stroke-dashoffset), eating each cell it reaches
    def px(p: tuple[int, int]) -> tuple[float, float]:
        return gx + p[0] * pitch + cell / 2, gy + p[1] * pitch + cell / 2

    route = snake_route(level, cols)
    dist, total, prev = {}, 0.0, route[0]
    for p in route[1:]:  # walk cell by cell, so every cell the snake touches gets eaten
        dx, dy = (p[0] > prev[0]) - (p[0] < prev[0]), (p[1] > prev[1]) - (p[1] < prev[1])
        while prev != p:
            prev = (prev[0] + dx, prev[1] + dy)
            total += pitch
            dist.setdefault(prev, total)
    body = 5 * pitch
    speed = 9 * pitch  # px per second
    move = total / speed
    cycle = move + 2.5  # pause with every cell eaten, then the grid refills and it starts over
    begin = start + 1.6
    path = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in map(px, route))

    cells = []
    for (col, row), lvl in level.items():
        x, y = gx + col * pitch, gy + row * pitch
        eat = ""
        if lvl and not STATIC:
            k = min(dist[(col, row)] / speed / cycle, .999)
            eat = (f'<animate attributeName="fill" values="{HEAT[lvl]};{HEAT[0]}" keyTimes="0;{k:.4f}" '
                   f'calcMode="discrete" dur="{cycle:.2f}s" begin="{begin:.2f}s" repeatCount="indefinite"/>')
        cells.append(f'<g{c.anim("pop", .15 + col * .02 + row * .015)}><rect x="{x:.1f}" y="{y:.1f}" '
                     f'width="{cell}" height="{cell}" rx="2.5" class="l{lvl}" fill="{HEAT[lvl]}">{eat}</rect></g>')
    c.add("".join(cells))
    # under reduced motion CSS outranks the SMIL fill changes, so cells keep their colour
    c.reduced = "".join(f".l{k}{{fill:{h}}}" for k, h in enumerate(HEAT))

    worm = (f'fill="none" stroke="{SNAKE}" stroke-width="{cell * .78:.1f}" stroke-linecap="round" '
            f'stroke-linejoin="round" d="{path}" stroke-dasharray="{body:.1f} {total + body:.1f}"')
    rest = body - 9 * pitch  # the still snake lies with its head a few cells into the grid
    c.motion(f'<path clip-path="url(#inside)" {worm} stroke-dashoffset="{body:.1f}">'
             f'<animate attributeName="stroke-dashoffset" values="{body:.1f};{body - total:.1f};{body - total:.1f}" '
             f'keyTimes="0;{move / cycle:.4f};1" dur="{cycle:.2f}s" begin="{begin:.2f}s" repeatCount="indefinite"/>'
             f'</path>',
             f'<path clip-path="url(#inside)" {worm} stroke-dashoffset="{rest:.1f}"/>')

    lx = 860 - 5 * pitch + (pitch - cell)
    legend = [c.text(lx - 8, 204, "menos", "m4", 9.5, DIM, "end")]
    legend += [f'<rect x="{lx + k * pitch:.1f}" y="{194.5}" width="{cell}" height="{cell}" rx="2.5" fill="{h}"/>'
               for k, h in enumerate(HEAT)]
    legend.append(c.text(lx + 5 * pitch + 4, 204, "mais", "m4", 9.5, DIM))
    shift = c.width("m4", "mais", 9.5) + 8  # keep "mais" inside the frame
    c.add(f'<g transform="translate({-shift:.1f} 0)"{c.anim("fade", 1)}>{"".join(legend)}</g>')
    c.save()


def shade(t: float) -> str:
    """A colour t (0..1) of the way along the green ladder."""
    x = t * (len(LADDER) - 1)
    i = min(int(x), len(LADDER) - 2)
    a, b = LADDER[i], LADDER[i + 1]
    mix = [round(int(a[k:k + 2], 16) * (1 - (x - i)) + int(b[k:k + 2], 16) * (x - i)) for k in (1, 3, 5)]
    return "#" + "".join(f"{v:02X}" for v in mix)


def cert(fonts: Fonts, idx: int, title: str, issuer: str, when: date, slug: str, start: float) -> None:
    """A compact certificate badge: rosette seal, issuer, title and date."""
    bg = shade(idx / max(len(CERTS) - 1, 1))
    dark = sum(int(bg[k:k + 2], 16) for k in (1, 3, 5)) / 3 < 110
    fg, fg2 = (ON_DARK, ON_DARK_DIM) if dark else (TEXT, LEAF)
    Wc, Hc = 300, 184
    day = f"{when.day:02d} {MONTHS[when.month - 1]} {when.year}"
    c = Card(fonts, f"cert-{slug}", Wc, Hc, start, f"Certificado: {title}, {issuer}, {day}")
    c.defs.append(f'<clipPath id="clip"><rect width="{Wc}" height="{Hc}" rx="16"/></clipPath>'
                  '<linearGradient id="gl" x1="0" x2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/>'
                  '<stop offset=".5" stop-color="#fff" stop-opacity=".35"/>'
                  '<stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>')
    c.add(f'<rect x=".75" y=".75" width="{Wc - 1.5}" height="{Hc - 1.5}" rx="16" fill="{bg}" stroke="{fg}" '
          f'stroke-opacity=".12"/>')
    c.add(f'<g clip-path="url(#clip)"><circle cx="{Wc - 30}" cy="{Hc + 10}" r="96" fill="{fg}" '
          f'fill-opacity=".06"{c.anim("pop", .15)}/></g>')

    # rosette seal with the step number
    cx, cy = 48, 48
    pts = []
    for k in range(32):
        r = 23 if k % 2 == 0 else 20.5
        a = math.pi * k / 16
        pts.append(f"{cx + r * math.cos(a):.1f},{cy + r * math.sin(a):.1f}")
    c.add(f'<g{c.anim("pop", .1)}><polygon points="{" ".join(pts)}" fill="{fg}" stroke="{fg}" '
          f'stroke-width="1.5" stroke-linejoin="round"/>'
          f'<circle cx="{cx}" cy="{cy}" r="15" fill="none" stroke="{bg}" stroke-width="1.4" stroke-opacity=".6"/>'
          + c.text(cx, cy + 5, f"{idx + 1:02d}", "m6", 13, bg, "middle") + "</g>")
    c.motion(f'<circle cx="{cx}" cy="{cy}" r="30" fill="none" stroke="{fg}" stroke-opacity=".35" '
             f'stroke-width="1.2" stroke-dasharray="2 5"><animateTransform attributeName="transform" '
             f'type="rotate" from="0 {cx} {cy}" to="360 {cx} {cy}" dur="24s" repeatCount="indefinite"/></circle>')

    # date pill and arrow, top right
    dw = c.width("m6", day, 11) + 20
    c.add(f'<g{c.anim("slide", .3)}><rect x="{Wc - 22 - dw:.1f}" y="24" width="{dw:.1f}" height="24" rx="12" '
          f'fill="{fg}" fill-opacity=".1"/>' + c.text(Wc - 22 - dw / 2, 40, day, "m6", 11, fg, "middle") + "</g>")

    c.add(f'<g{c.anim("rise", .2)}>' + c.text(24, 104, issuer.upper(), "m6", 11.5, fg2, ls=1) + "</g>")
    lines = wrap(c, title, "q7", 19, Wc - 48, 2)
    c.add(f'<g{c.anim("rise", .28)}>' + "".join(
        c.text(24, 132 + 24 * j, ln, "q7", 19, fg) for j, ln in enumerate(lines)) + "</g>")

    # one light sweep across the badge as it lands
    if not STATIC:
        c.add(f'<g clip-path="url(#clip)"><g transform="skewX(-18)"><rect{c.anim("shine", .45)} x="-200" y="-40" '
              f'width="110" height="{Hc + 80}" fill="url(#gl)"/></g></g>')
    c.save()


def preview() -> None:
    img = lambda n, w: f'<img src="{n}.svg" width="{w}">'
    tiles = "".join(img(f"tile-{t[0]}", "32.5%") for t in TILES)
    repos = "".join(img(f"repo-{n.lower()}", "49.3%") for n, _ in FEATURED)
    certs = "".join(img(f"cert-{x[0]}", "24.5%") for x in CERTS)
    rows = [img("hero", "100%"), f'<div class="row">{tiles}</div>', img("studies", "100%"),
            img("contributions-monthly", "100%"), f'<div class="row wrap">{repos}</div>', img("contribution-graph", "100%"),
            f'<div class="row wrap">{certs}</div>']
    (OUT / "index.html").write_text(
        "<!doctype html><meta charset=utf-8><title>cards preview</title><style>body{background:#0d1117;"
        "margin:0;padding:32px}main{max-width:830px;margin:auto;display:grid;gap:8px}"
        ".row{display:flex;justify-content:space-between}.wrap{flex-wrap:wrap;row-gap:8px}img{display:block}</style><main>"
        + "".join(rows) + "</main>\n")


def render() -> None:
    data = load()
    days = [(date.fromisoformat(d), c) for d, c in data["days"]]
    if not days:
        sys.exit("no contribution days in data/github.json")
    s = stats(days)  # the whole year, for the contribution graph
    chart = stats([d for d in days if d[0] >= CHART_FROM] or days[-1:])
    OUT.mkdir(exist_ok=True)
    fonts = Fonts()
    print(f"rendering {'final frame' if STATIC else 'animated'} cards into {OUT.relative_to(ROOT)}/")
    try:
        t = 0.0  # every card starts a little after the one above it
        hero(fonts, t)
        t += .7
        for i, (slug, title, sub, ico) in enumerate(TILES):
            tile(fonts, i, slug, title, sub.format(repos=data["user"]["public_repos"], certs=len(CERTS)), ico, t + i * .15)
        t += .8
        studies(fonts, t)
        t += 1
        monthly(fonts, chart, t)
        t += .9
        for i, (name, blurb) in enumerate(FEATURED, 1):
            repo(fonts, i, name, blurb, data["repos"].get(name, {}), t + (i - 1) % 2 * .15)
            if i % 2 == 0:
                t += .35
        graph(fonts, days, s, t)
        t += 2.2
        for i, (slug, title, issuer, when, _) in enumerate(CERTS):
            cert(fonts, i, title, issuer, when, slug, t + i % 4 * .12 + i // 4 * .3)
    finally:
        fonts.close()
    if STATIC:
        preview()
        print(f"  open {(OUT / 'index.html').relative_to(ROOT)} to screenshot the final frame")


if __name__ == "__main__":
    cmd = sys.argv[1:2]
    fetch() if cmd == ["fetch"] else render()
