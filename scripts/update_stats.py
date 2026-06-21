#!/usr/bin/env python3
"""
Atualiza o bloco <!--START_SECTION:status--> do README com dados ao vivo
do GitHub: idade, repositórios, commits, estrelas e linhas de código.

Uso (local):
    GH_TOKEN=ghp_xxx USER_NAME=daniel-fbo python scripts/update_stats.py

No GitHub Actions o GH_TOKEN vem de um secret (ver SETUP.md).
"""

import os
import re
import sys
import json
import datetime
import pathlib

import requests

# ──────────────────────────────────────────────────────────────────────────
# Configuração
# ──────────────────────────────────────────────────────────────────────────

USER = os.environ.get("USER_NAME", "daniel-fbo")
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")

# >>> AJUSTE AQUI: sua data de nascimento (ano, mês, dia) <<<
BIRTHDAY = datetime.date(2007,7, 1)

README = pathlib.Path("README.md")
CACHE = pathlib.Path("cache/loc_cache.json")
API = "https://api.github.com/graphql"

if not TOKEN:
    sys.exit("ERRO: defina GH_TOKEN (ou GITHUB_TOKEN) no ambiente.")

HEADERS = {"Authorization": f"bearer {TOKEN}"}


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────

def gql(query, variables=None):
    """Executa uma query GraphQL e devolve o nó `data`."""
    resp = requests.post(
        API,
        json={"query": query, "variables": variables or {}},
        headers=HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    return payload["data"]


def human_age(bday):
    """Retorna (anos, dias) desde a data de nascimento."""
    today = datetime.date.today()
    years = today.year - bday.year - ((today.month, today.day) < (bday.month, bday.day))
    last_birthday = bday.replace(year=bday.year + years)
    days = (today - last_birthday).days
    return years, days


# ──────────────────────────────────────────────────────────────────────────
# Queries
# ──────────────────────────────────────────────────────────────────────────

Q_OVERVIEW = """
query($login: String!) {
  user(login: $login) {
    id
    repositories(first: 100, isFork: false, ownerAffiliations: [OWNER],
                 orderBy: {field: STARGAZERS, direction: DESC}) {
      totalCount
      nodes { nameWithOwner stargazerCount }
    }
    repositoriesContributedTo(first: 100,
                              contributionTypes: [COMMIT, PULL_REQUEST]) {
      totalCount
      nodes { nameWithOwner }
    }
  }
}
"""

Q_COUNT = """
query($owner: String!, $name: String!, $id: ID!) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      target { ... on Commit { history(author: {id: $id}) { totalCount } } }
    }
  }
}
"""

Q_HISTORY = """
query($owner: String!, $name: String!, $id: ID!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      target {
        ... on Commit {
          history(first: 100, author: {id: $id}, after: $cursor) {
            totalCount
            pageInfo { hasNextPage endCursor }
            nodes { additions deletions }
          }
        }
      }
    }
  }
}
"""


def commit_count(owner, name, uid):
    """Número de commits do usuário no branch padrão (barato: 1 query)."""
    data = gql(Q_COUNT, {"owner": owner, "name": name, "id": uid})
    ref = data["repository"]["defaultBranchRef"]
    if not ref or not ref.get("target"):
        return 0
    return ref["target"]["history"]["totalCount"]


def walk_repo(owner, name, uid):
    """Caminha todo o histórico do usuário: (commits, additions, deletions)."""
    add = dele = commits = 0
    cursor = None
    while True:
        data = gql(Q_HISTORY, {"owner": owner, "name": name, "id": uid, "cursor": cursor})
        ref = data["repository"]["defaultBranchRef"]
        if not ref or not ref.get("target"):
            break
        hist = ref["target"]["history"]
        commits = hist["totalCount"]
        for node in hist["nodes"]:
            add += node["additions"]
            dele += node["deletions"]
        if hist["pageInfo"]["hasNextPage"]:
            cursor = hist["pageInfo"]["endCursor"]
        else:
            break
    return commits, add, dele


# ──────────────────────────────────────────────────────────────────────────
# README
# ──────────────────────────────────────────────────────────────────────────

def build_block(years, days, repos, commits, stars, contrib, add, dele):
    net = add - dele
    today = datetime.date.today().isoformat()
    lines = [
        "```console",
        "$ daniel.fbo --status",
        "",
        f"  idade ............. {years} anos, {days} dias",
        f"  repositórios ...... {repos}",
        f"  commits ........... {commits:,}".replace(",", "."),
        f"  estrelas .......... {stars}",
        f"  contribuiu em ..... {contrib} repositórios",
        f"  linhas de código .. {net:,}  (+{add:,} / -{dele:,})".replace(",", "."),
        "",
        f"  última atualização  {today}  ·  auto via GitHub Actions",
        "```",
    ]
    return "\n".join(lines)


def replace_section(text, key, content):
    pattern = re.compile(
        rf"(<!--START_SECTION:{key}-->)(.*?)(<!--END_SECTION:{key}-->)", re.S
    )
    return pattern.sub(lambda m: f"{m.group(1)}\n{content}\n{m.group(3)}", text)


# ──────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────

def main():
    text = README.read_text(encoding="utf-8")

    user = gql(Q_OVERVIEW, {"login": USER})["user"]
    uid = user["id"]
    owned = user["repositories"]["nodes"]
    repos_count = user["repositories"]["totalCount"]
    stars = sum(r["stargazerCount"] for r in owned)
    contrib = user["repositoriesContributedTo"]["totalCount"]

    # repositórios a varrer para commits + LOC (próprios + contribuídos)
    scan = {r["nameWithOwner"] for r in owned}
    scan |= {r["nameWithOwner"] for r in user["repositoriesContributedTo"]["nodes"]}

    cache = {}
    if CACHE.exists():
        try:
            cache = json.loads(CACHE.read_text())
        except Exception:
            cache = {}

    total_commits = total_add = total_del = 0
    fresh = {}

    for full in sorted(scan):
        owner, name = full.split("/", 1)
        try:
            count = commit_count(owner, name, uid)
        except Exception:
            continue
        if count == 0:
            continue

        cached = cache.get(full)
        if cached and cached.get("commits") == count:
            # nada mudou desde a última corrida — reaproveita o cache
            c, a, d = count, cached["add"], cached["del"]
        else:
            try:
                c, a, d = walk_repo(owner, name, uid)
            except Exception:
                if cached:
                    c, a, d = cached["commits"], cached["add"], cached["del"]
                else:
                    continue

        fresh[full] = {"commits": c, "add": a, "del": d}
        total_commits += c
        total_add += a
        total_del += d

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(fresh, indent=2))

    years, days = human_age(BIRTHDAY)
    block = build_block(
        years, days, repos_count, total_commits, stars, contrib, total_add, total_del
    )
    new_text = replace_section(text, "status", block)

    if new_text != text:
        README.write_text(new_text, encoding="utf-8")
        print("README atualizado.")
    else:
        print("Nenhuma mudança no README.")


if __name__ == "__main__":
    main()
