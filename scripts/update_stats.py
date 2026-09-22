import datetime
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

USER = os.environ.get("USER_NAME", "daniel-fbo")
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
README = pathlib.Path("README.md")
CACHE = pathlib.Path("cache/loc_cache.json")
ASSETS = pathlib.Path("assets")
TOP_N = 8

EXT_TO_LANG = {
    ".py": "Python", ".ipynb": "Jupyter Notebook",
    ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin",
    ".c": "C", ".h": "C", ".cpp": "C++", ".cc": "C++", ".hpp": "C++",
    ".cs": "C#", ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".php": "PHP",
    ".html": "HTML", ".css": "CSS", ".scss": "SCSS",
    ".sh": "Shell", ".sql": "SQL", ".dart": "Dart", ".lua": "Lua",
    ".swift": "Swift", ".vue": "Vue", ".r": "R", ".hs": "Haskell",
}

LANG_COLORS = {
    "Python": "#3572A5", "Jupyter Notebook": "#DA5B0B", "JavaScript": "#f1e05a",
    "TypeScript": "#3178c6", "Java": "#b07219", "Kotlin": "#A97BFF",
    "C": "#555555", "C++": "#f34b7d", "C#": "#178600", "Go": "#00ADD8",
    "Rust": "#dea584", "Ruby": "#701516", "PHP": "#4F5D95", "HTML": "#e34c26",
    "CSS": "#563d7c", "SCSS": "#c6538c", "Shell": "#89e051", "SQL": "#e38c00",
    "Dart": "#00B4AB", "Lua": "#000080", "Swift": "#F05138", "Vue": "#41b883",
    "R": "#198CE7", "Haskell": "#5e5086",
}

Q_OVERVIEW = """
query($login: String!) {
  user(login: $login) {
    id
    repositories(first: 100, isFork: false, ownerAffiliations: [OWNER]) {
      totalCount
      nodes { nameWithOwner stargazerCount }
    }
    repositoriesContributedTo(first: 100, contributionTypes: [COMMIT, PULL_REQUEST]) {
      totalCount
      nodes { nameWithOwner }
    }
  }
}
"""

Q_HISTORY = """
query($owner: String!, $name: String!, $id: ID!, $cursor: String, $first: Int!) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      target {
        ... on Commit {
          history(first: $first, author: {id: $id}, after: $cursor) {
            totalCount
            pageInfo { hasNextPage endCursor }
            nodes { additions deletions author { email } }
          }
        }
      }
    }
  }
}
"""


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def gql(query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                "https://api.github.com/graphql",
                data=body,
                headers={"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.load(resp)
            if "errors" in payload:
                raise RuntimeError(payload["errors"])
            return payload["data"]
        except Exception as exc:
            if attempt == 2:
                raise
            log(f"tentativa {attempt + 1} falhou: {exc}")
            time.sleep(2 ** (attempt + 1))


def history(owner, name, uid, first, cursor=None):
    data = gql(Q_HISTORY, {"owner": owner, "name": name, "id": uid, "cursor": cursor, "first": first})
    ref = data["repository"]["defaultBranchRef"]
    return ref["target"]["history"] if ref and ref.get("target") else None


def walk_repo(owner, name, uid):
    add = dele = commits = 0
    emails = set()
    cursor = None
    while True:
        hist = history(owner, name, uid, 100, cursor)
        if not hist:
            break
        commits = hist["totalCount"]
        for node in hist["nodes"]:
            add += node["additions"]
            dele += node["deletions"]
            if node["author"] and node["author"]["email"]:
                emails.add(node["author"]["email"])
        if not hist["pageInfo"]["hasNextPage"]:
            break
        cursor = hist["pageInfo"]["endCursor"]
    return commits, add, dele, emails


def repo_languages(full, emails, tmp):
    dest = os.path.join(tmp, full.replace("/", "__"))
    url = f"https://x-access-token:{TOKEN}@github.com/{full}.git"
    subprocess.run(["git", "clone", "--bare", "-q", url, dest], check=True, capture_output=True)
    cmd = ["git", "-C", dest, "log", "HEAD", "--no-merges", "-F", "--pretty=format:", "--numstat"]
    cmd += [f"--author={e}" for e in emails]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    langs = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 3 or parts[0] == "-":
            continue
        lang = EXT_TO_LANG.get(os.path.splitext(parts[2])[1].lower())
        if lang:
            langs[lang] = langs.get(lang, 0) + int(parts[0])
    return langs


def build_block(repos, commits, stars, contrib, add, dele):
    fmt = lambda n: f"{n:,}".replace(",", ".")
    return "\n".join([
        "```console",
        "$ daniel.fbo --status",
        f"  repositórios ...... {repos}",
        f"  commits ........... {fmt(commits)}",
        f"  estrelas .......... {stars}",
        f"  contribuiu em ..... {contrib} repositórios",
        f"  linhas de código .. {fmt(add - dele)}  (+{fmt(add)} / -{fmt(dele)})",
        "",
        f"  última atualização  {datetime.date.today().isoformat()}  ·  auto via GitHub Actions",
        "```",
    ])


def build_svg(percentages, title_color, text_color):
    font = "font-family=\"'Segoe UI', Ubuntu, sans-serif\" font-size=\"12\""
    rows = []
    y = 40
    for lang, pct in percentages:
        color = LANG_COLORS.get(lang, "#d4af37")
        rows.append(
            f'<text x="0" y="{y - 6}" {font} fill="{text_color}">{lang}</text>'
            f'<text x="280" y="{y - 6}" {font} fill="{text_color}" text-anchor="end">{pct:.1f}%</text>'
            f'<rect x="0" y="{y}" width="280" height="6" rx="3" fill="{text_color}" opacity="0.15"/>'
            f'<rect x="0" y="{y}" width="{max(2, pct / 100 * 280):.1f}" height="6" rx="3" fill="{color}"/>'
        )
        y += 30
    height = 40 + 30 * len(percentages)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="300" height="{height}" viewBox="0 0 300 {height}">'
        f"<text x=\"10\" y=\"20\" font-family=\"'Segoe UI', Ubuntu, sans-serif\" font-size=\"16\" "
        f'font-weight="600" fill="{title_color}">Linguagens mais usadas</text>'
        f'<g transform="translate(10, 0)">{"".join(rows)}</g></svg>\n'
    )


def main():
    if not TOKEN:
        sys.exit("defina GH_TOKEN")

    user = gql(Q_OVERVIEW, {"login": USER})["user"]
    uid = user["id"]
    owned = user["repositories"]["nodes"]
    contributed = user["repositoriesContributedTo"]["nodes"]
    scan = sorted({r["nameWithOwner"] for r in owned + contributed})

    try:
        cache = json.loads(CACHE.read_text())
    except Exception:
        cache = {}

    fresh = {}
    with tempfile.TemporaryDirectory() as tmp:
        for full in scan:
            owner, name = full.split("/", 1)
            try:
                hist = history(owner, name, uid, 1)
                count = hist["totalCount"] if hist else 0
                if count == 0:
                    continue
                cached = cache.get(full)
                if cached and cached.get("commits") == count and "languages" in cached:
                    fresh[full] = cached
                    continue
                commits, add, dele, emails = walk_repo(owner, name, uid)
                langs = repo_languages(full, emails, tmp) if emails else {}
                fresh[full] = {"commits": commits, "add": add, "del": dele, "languages": langs}
            except Exception as exc:
                log(f"::warning::{full}: {exc}")
                if full in cache:
                    fresh[full] = cache[full]

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(fresh, indent=2, ensure_ascii=False) + "\n")

    total = lambda key: sum(r[key] for r in fresh.values())
    block = build_block(
        user["repositories"]["totalCount"],
        total("commits"),
        sum(r["stargazerCount"] for r in owned),
        user["repositoriesContributedTo"]["totalCount"],
        total("add"),
        total("del"),
    )
    text = README.read_text(encoding="utf-8")
    text = re.sub(
        r"(<!--START_SECTION:status-->).*?(<!--END_SECTION:status-->)",
        lambda m: f"{m.group(1)}\n{block}\n{m.group(2)}",
        text,
        flags=re.S,
    )
    README.write_text(text, encoding="utf-8")

    langs = {}
    for repo in fresh.values():
        for lang, n in repo.get("languages", {}).items():
            langs[lang] = langs.get(lang, 0) + n
    lang_total = sum(langs.values())
    if lang_total:
        ranked = sorted(langs.items(), key=lambda kv: kv[1], reverse=True)[:TOP_N]
        percentages = [(lang, n / lang_total * 100) for lang, n in ranked]
        ASSETS.mkdir(exist_ok=True)
        (ASSETS / "lang-stats-dark.svg").write_text(build_svg(percentages, "#d4af37", "#9ba3af"))
        (ASSETS / "lang-stats-light.svg").write_text(build_svg(percentages, "#8a6d1b", "#4b5563"))


if __name__ == "__main__":
    main()
