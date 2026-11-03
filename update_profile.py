"""Regenerate dark_mode.svg / light_mode.svg with live GitHub stats.

Runs daily via GitHub Actions. Stdlib only, no dependencies.
"""
import calendar
import html
import json
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

USER = "realchendahuang"
JOINED = date(2024, 4, 11)  # account creation date, shown as "Uptime"
JOINED_YEAR = 2024
W = 56  # info column width in characters

ART = r"""
                -++*++++=-
               -+******++++=
             -++++++++++-=+++.
             =+++=-==---:---=:
              *=-----::---::::
              -=---------:::.:.
              .--:::-:.::::..:
               ::::::-:::::...
                :::::---::::.
                  :--::::.::.
                   :-----:::..
                  ::-----:::..==-:
              -=+*-::::::::..:*****+==-:
          :=+*##***+=-::::::-***********+=
        =+*********###*++++#%*#****##*****=
      -******#*##***########*##*########***=
     :****####*##****##***###%*#*########***-
     =***########*****##*#####*#*########***=
     ***#########******#####%*######@%%%#***+
    =****#####*##*******###@#*#####@*-=+#***+
    +***#***######********%%#####*%+:-:=#*##*
    +********######******#%#######*::::-#+=--
   -*********#%%#####****########@-::::=-:..
"""

# two tokens by design: the Actions GITHUB_TOKEN yields the contribution-style
# commit count (public + private activity), while a PAT (ACCESS_TOKEN secret)
# sees private repos for the repo list and LOC walk. Either falls back to the other.
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("ACCESS_TOKEN") or ""
PRIV_TOKEN = os.environ.get("ACCESS_TOKEN") or TOKEN


def gh(url, payload=None, token=None):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode() if payload else None,
        headers={"Authorization": f"Bearer {token or TOKEN}", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req) as r:
        return r.status, json.loads(r.read() or "{}")


def graphql(query, variables=None, token=None):
    _, resp = gh("https://api.github.com/graphql", {"query": query, "variables": variables or {}}, token)
    if resp.get("errors"):
        raise RuntimeError(resp["errors"])
    return resp["data"]


def age(b, t):
    years = t.year - b.year - ((t.month, t.day) < (b.month, b.day))
    months = (t.month - b.month - (t.day < b.day)) % 12
    if t.day >= b.day:
        days = t.day - b.day
    else:
        pm_year, pm = (t.year, t.month - 1) if t.month > 1 else (t.year - 1, 12)
        days = calendar.monthrange(pm_year, pm)[1] - b.day + t.day
    return years, months, days


def repo_scope():
    # Without a PAT a token only sees public repos anyway; stating it explicitly keeps
    # local runs and CI showing the same numbers instead of flip-flopping every night.
    return "" if os.environ.get("ACCESS_TOKEN") else ", privacy: PUBLIC"


def fetch_stats():
    yr_aliases = "\n".join(
        f'y{y}: contributionsCollection(from: "{y}-01-01T00:00:00Z", to: "{y + 1}-01-01T00:00:00Z")'
        " { totalCommitContributions restrictedContributionsCount }"
        for y in range(JOINED_YEAR, datetime.now(timezone.utc).year + 1)
    )
    contrib = graphql(f'query {{ user(login: "{USER}") {{ {yr_aliases} }} }}')["user"]
    commits = sum(
        v["totalCommitContributions"] + v["restrictedContributionsCount"]
        for v in contrib.values()
    )
    u = graphql(f"""
    query {{
      user(login: "{USER}") {{
        id
        followers {{ totalCount }}
        repositories(first: 100, ownerAffiliations: OWNER{repo_scope()}) {{
          totalCount
          nodes {{ name stargazerCount isFork }}
        }}
        repositoriesContributedTo(first: 1, contributionTypes: [COMMIT, PULL_REQUEST, REPOSITORY]) {{
          totalCount
        }}
      }}
    }}""", token=PRIV_TOKEN)["user"]
    stats = {
        "followers": u["followers"]["totalCount"],
        "repos": public_repos(),
        "contributed": u["repositoriesContributedTo"]["totalCount"],
        "stars": sum(n["stargazerCount"] for n in u["repositories"]["nodes"]),
        "commits": commits,
        "user_id": u["id"],
        "repo_names": [n["name"] for n in u["repositories"]["nodes"] if not n["isFork"]],
    }
    stats.update(loc(stats["repo_names"], stats["user_id"]))
    return stats


def public_repos():
    # GraphQL repositories{} counts private repos too; the profile header shows the public one
    _, resp = gh(f"https://api.github.com/users/{USER}")
    return resp["public_repos"]


LOC_QUERY = """
query($owner: String!, $name: String!, $id: ID!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef { target { ... on Commit {
      history(first: 100, author: {id: $id}, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes { additions deletions }
      }
    } } }
  }
}"""


def _retry(fn, tries=4):
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            if i == tries - 1:
                raise
            print(f"retry {i + 1}: {e}")
            time.sleep(2 * (i + 1))


def scan_repo(name, user_id):
    add = rem = 0
    cursor = None
    try:
        while True:
            ref = _retry(lambda c=cursor: graphql(
                LOC_QUERY, {"owner": USER, "name": name, "id": user_id, "cursor": c},
                token=PRIV_TOKEN))["repository"]["defaultBranchRef"]
            if ref is None:
                break  # empty repo
            h = ref["target"]["history"]
            add += sum(n["additions"] for n in h["nodes"])
            rem += sum(n["deletions"] for n in h["nodes"])
            if not h["pageInfo"]["hasNextPage"]:
                break
            cursor = h["pageInfo"]["endCursor"]
    except Exception as e:
        print(f"loc {name}: {e}")
    return add, rem


def loc(repo_names, user_id):
    # ponytail: REST stats/contributors answers 202 forever to the Actions token,
    # so walk own commits on the default branch via GraphQL instead.
    # Parallel because a hundred+ repos of paginated history is otherwise minutes of wall clock.
    add = rem = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        for a, r in pool.map(lambda n: scan_repo(n, user_id), repo_names):
            add += a
            rem += r
    return {"loc_add": add, "loc_del": rem, "loc": add - rem}


PALETTES = {
    "dark": {"bg": "#0d1117", "border": "#30363d", "art": "#8b949e", "h": "#58a6ff",
             "k": "#ffa657", "v": "#c9d1d9", "d": "#484f58", "g": "#3fb950", "r": "#f85149"},
    "light": {"bg": "#ffffff", "border": "#d0d7de", "art": "#57606a", "h": "#0969da",
              "k": "#953800", "v": "#24292f", "d": "#afb8c1", "g": "#1a7f37", "r": "#cf222e"},
}


def kv(key, val, width=W):
    dots = "." * max(width - len(key) - len(str(val)) - 3, 1)
    return [(f"{key}: ", "k"), (dots + " ", "d"), (str(val), "v")]


def kv2(k1, v1, k2, v2):
    left = kv(k1, v1, 30)
    return left + [(" | ", "d")] + kv(k2, v2, 23)


def rule(title=""):
    label = f"─ {title} " if title else ""
    return [(label, "h"), ("─" * (W - len(label)), "d")]


def info_lines(s):
    y, m, d = age(JOINED, date.today())
    n = lambda x: f"{x:,}"
    return [
        [(f"{USER.lower()}@github ", "h"), ("─" * (W - len(USER) - 8), "d")],
        [],
        kv("OS", "macOS (Apple Silicon)"),
        kv("Uptime", f"{y} years, {m} months, {d} days"),
        kv("Host", "Indie Hacker"),
        kv("Kernel", "AI Products · Cloudflare"),
        kv("IDE", "ZCode, Claude Code, Ghostty"),
        [],
        kv("Languages.Programming", "TypeScript, Python, Go, Shell"),
        kv("Languages.Real", "Chinese, English"),
        kv("Currently", "FlareMo, FeedSieve, Cherina Pod"),
        [],
        rule("Contact"),
        kv("Email", "chendanhuang31016@gmail.com"),
        kv("Site", "chendahuang.com"),
        kv("X", "@realchendahuang"),
        [],
        rule("GitHub Stats"),
        kv2("Repos", f"{s['repos']} {{Contributed: {s['contributed']}}}", "Stars", n(s["stars"])),
        kv2("Commits", n(s["commits"]), "Followers", n(s["followers"])),
        [("Lines of Code: ", "k"), (n(s["loc"]), "v"), (" ( ", "d"),
         (n(s["loc_add"]) + "++", "g"), (", ", "d"), (n(s["loc_del"]) + "--", "r"), (" )", "d")],
    ]


def render(mode, stats):
    p = PALETTES[mode]
    out = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="840" height="500" viewBox="0 0 840 500" '
        f'font-family="Consolas, Menlo, monospace" font-size="13px">',
        f'<rect x="0.5" y="0.5" width="839" height="499" rx="10" fill="{p["bg"]}" stroke="{p["border"]}"/>',
    ]
    art_lines = ART.strip("\n").split("\n")
    art_top = 40 + max((500 - 40 - len(art_lines) * 15) // 2, 0)
    for i, line in enumerate(art_lines):
        out.append(f'<text x="25" y="{art_top + i * 15}" fill="{p["art"]}" xml:space="preserve">{html.escape(line)}</text>')
    for i, segs in enumerate(info_lines(stats)):
        if not segs:
            continue
        spans = "".join(f'<tspan fill="{p[c]}">{html.escape(t)}</tspan>' for t, c in segs)
        out.append(f'<text x="390" y="{45 + i * 21}" xml:space="preserve">{spans}</text>')
    out.append("</svg>")
    return "\n".join(out)


def selfcheck():
    assert age(date(2024, 4, 11), date(2026, 11, 3)) == (2, 6, 23)
    assert len("".join(t for t, _ in kv("OS", "macOS (Apple Silicon)"))) == W
    assert max(len(l) for l in ART.strip("\n").split("\n")) <= 50, "art too wide for the 390px info gutter"


if __name__ == "__main__":
    selfcheck()
    stats = fetch_stats()
    print("stats:", {k: v for k, v in stats.items() if k != "repo_names"})
    os.makedirs("img", exist_ok=True)
    for mode in PALETTES:
        with open(f"img/{mode}.svg", "w", encoding="utf-8") as f:
            f.write(render(mode, stats))
    print("wrote img/dark.svg, img/light.svg")
