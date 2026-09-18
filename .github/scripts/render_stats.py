#!/usr/bin/env python3
"""Render assets/github-stats.svg from live GitHub data.

Reads assets/github-stats.template.svg, substitutes the five {{...}}
placeholders with numbers pulled from the GitHub GraphQL API, and writes
assets/github-stats.svg. Runs in CI, so the committed SVG is what the
README serves (no third-party runtime at view time).
"""
import datetime
import json
import os
import urllib.request

USER = "k-kohli10"
API = "https://api.github.com/graphql"
TOKEN = os.environ["METRICS_TOKEN"]

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
TEMPLATE = os.path.join(REPO, "assets", "github-stats.template.svg")
OUTPUT = os.path.join(REPO, "assets", "github-stats.svg")


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
