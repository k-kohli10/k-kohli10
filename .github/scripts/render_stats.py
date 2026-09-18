#!/usr/bin/env python3
"""Render assets/github-stats.svg from live GitHub data.

Reads assets/github-stats.template.svg, substitutes the five {{...}}
placeholders with numbers pulled from the GitHub GraphQL API, and writes
assets/github-stats.svg. Runs in CI, so the committed SVG is what the
README serves (no third-party runtime at view time).
"""
import datetime
import json
import math
import os
import urllib.request

USER = "k-kohli10"
API = "https://api.github.com/graphql"
TOKEN = os.environ["METRICS_TOKEN"]

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
TEMPLATE = os.path.join(REPO, "assets", "github-stats.template.svg")
OUTPUT = os.path.join(REPO, "assets", "github-stats.svg")
LANGS_OUTPUT = os.path.join(REPO, "assets", "github-langs.svg")

# Curated donut palette, harmonised with the profile's orange/teal/pink accents.
# Assigned by language rank so the card reads as one system.
PALETTE = ["#ff8a4c", "#4dd0c4", "#f778ba", "#e3b341", "#b9a6ff"]
OTHER_COLOR = "#5b6270"

# Recognisable brand colors for specific languages override the palette.
LANG_COLORS = {"Python": "#3776AB"}


def gql(query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        API,
        data=body,
        headers={
            "Authorization": f"bearer {TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": USER,
        },
    )
    with urllib.request.urlopen(req) as resp:
        out = json.load(resp)
    if out.get("errors"):
        raise SystemExit(f"GraphQL errors: {out['errors']}")
    return out["data"]


def fmt(n):
    if n >= 1000:
        return f"{n / 1000:.1f}".rstrip("0").rstrip(".") + "k"
    return str(n)


# One-shot profile totals (stars summed over owned, non-fork repos).
base = gql(
    """
    query($login:String!){
      user(login:$login){
        createdAt
        pullRequests{ totalCount }
        issues{ totalCount }
        contributionsCollection{ totalRepositoriesWithContributedCommits }
        repositories(first:100, ownerAffiliations:OWNER, isFork:false){
          nodes{ stargazerCount }
        }
      }
    }
    """,
    {"login": USER},
)["user"]

stars = sum(n["stargazerCount"] for n in base["repositories"]["nodes"])
prs = base["pullRequests"]["totalCount"]
issues = base["issues"]["totalCount"]
contribs = base["contributionsCollection"]["totalRepositoriesWithContributedCommits"]

# All-time commits: sum yearly contribution windows since account creation.
# restrictedContributionsCount adds private commits when the profile setting
# "Include private contributions" is enabled; otherwise it is 0.
start_year = int(base["createdAt"][:4])
this_year = datetime.datetime.now(datetime.timezone.utc).year
commits = 0
for year in range(start_year, this_year + 1):
    cc = gql(
        """
        query($login:String!,$from:DateTime!,$to:DateTime!){
          user(login:$login){
            contributionsCollection(from:$from,to:$to){
              totalCommitContributions
              restrictedContributionsCount
            }
          }
        }
        """,
        {"login": USER, "from": f"{year}-01-01T00:00:00Z", "to": f"{year}-12-31T23:59:59Z"},
    )["user"]["contributionsCollection"]
    commits += cc["totalCommitContributions"] + cc["restrictedContributionsCount"]

values = {
    "{{STARS}}": fmt(stars),
    "{{COMMITS}}": fmt(commits),
    "{{PRS}}": fmt(prs),
    "{{ISSUES}}": fmt(issues),
    "{{CONTRIBS}}": fmt(contribs),
}

with open(TEMPLATE, encoding="utf-8") as f:
    svg = f.read()
for key, val in values.items():
    svg = svg.replace(key, val)
with open(OUTPUT, "w", encoding="utf-8") as f:
    f.write(svg)

print("Rendered github-stats.svg:", values)


# ---------------------------------------------------------------------------
# Most Used Languages card (pie chart + legend), same style as the stats card.
# ---------------------------------------------------------------------------
lang_repos = gql(
    """
    query($login:String!){
      user(login:$login){
        repositories(first:100, ownerAffiliations:OWNER, isFork:false){
          nodes{
            languages(first:10, orderBy:{field:SIZE, direction:DESC}){
              edges{ size node{ name } }
            }
          }
        }
      }
    }
    """,
    {"login": USER},
)["user"]["repositories"]["nodes"]

sizes = {}
for repo in lang_repos:
    for edge in repo["languages"]["edges"]:
        name = edge["node"]["name"]
        sizes[name] = sizes.get(name, 0) + edge["size"]

total_bytes = sum(sizes.values()) or 1
ranked = sorted(sizes.items(), key=lambda kv: kv[1], reverse=True)
top = ranked[:4]
other = sum(v for _, v in ranked[4:])

segments = []
palette_i = 0
for name, size in top:
    if name in LANG_COLORS:
        color = LANG_COLORS[name]
    else:
        color = PALETTE[palette_i % len(PALETTE)]
        palette_i += 1
    segments.append((name, size / total_bytes * 100, color))
if other > 0:
    segments.append(("Other", other / total_bytes * 100, OTHER_COLOR))


def arc(cx, cy, r, a0, a1, color, width):
    """A donut segment: a stroked arc along radius r (no fill)."""
    if a1 - a0 >= 2 * math.pi - 1e-6:
        return (
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
            f'stroke="{color}" stroke-width="{width}"/>'
        )
    x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
    x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
    large = 1 if (a1 - a0) > math.pi else 0
    return (
        f'<path d="M{x0:.2f} {y0:.2f} A{r} {r} 0 {large} 1 {x1:.2f} {y1:.2f}" '
        f'fill="none" stroke="{color}" stroke-width="{width}"/>'
    )


CX, CY, R, RING = 95, 110, 44, 16
GAP = math.radians(1.5)  # small separator between slices
wedges = ['<circle cx="%d" cy="%d" r="%d" fill="none" stroke="#21262d" stroke-width="%d"/>' % (CX, CY, R, RING)]
angle = -math.pi / 2
multi = len([s for s in segments if s[1] > 0]) > 1
for _, pct, color in segments:
    span = pct / 100 * 2 * math.pi
    a0 = angle + (GAP / 2 if multi else 0)
    a1 = angle + span - (GAP / 2 if multi else 0)
    if a1 > a0:
        wedges.append(arc(CX, CY, R, a0, a1, color, RING))
    angle += span

legend = []
ly = 74
for name, pct, color in segments:
    legend.append(f'<rect x="175" y="{ly - 10}" width="11" height="11" rx="2" fill="{color}"/>')
    legend.append(f'<text x="193" y="{ly}" class="stat">{name}</text>')
    legend.append(f'<text x="315" y="{ly}" class="stat" text-anchor="end">{pct:.1f}%</text>')
    ly += 21

langs_svg = f"""<svg width="340" height="180" viewBox="0 0 340 180" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="langDescId">
  <title id="langTitleId">Most Used Languages</title>
  <desc id="langDescId">{", ".join(f"{n} {p:.1f}%" for n, p, _ in segments)}</desc>
  <style>
    .header {{ font: 600 18px 'Segoe UI', Ubuntu, Sans-Serif; fill: #b9a6ff; }}
    @supports(-moz-appearance: auto) {{ .header {{ font-size: 15.5px; }} }}
    .stat {{ font: 600 14px 'Segoe UI', Ubuntu, "Helvetica Neue", Sans-Serif; fill: #c9d1d9; }}
    @supports(-moz-appearance: auto) {{ .stat {{ font-size: 12px; }} }}
  </style>
  <rect x="0.5" y="0.5" rx="10" height="179" stroke="#30363d" width="339" fill="#0d1117"/>
  <text x="25" y="35" class="header">Most Used Languages</text>
  {"".join(wedges)}
  {"".join(legend)}
</svg>
"""

with open(LANGS_OUTPUT, "w", encoding="utf-8") as f:
    f.write(langs_svg)

print("Rendered github-langs.svg:", [(n, round(p, 1)) for n, p, _ in segments])
