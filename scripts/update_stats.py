#!/usr/bin/env python3
"""
Atualiza o bloco <!--START_SECTION:status--> do README com dados ao vivo
do GitHub: idade, repositórios, commits, estrelas e linhas de código.

Uso (local):
    GH_TOKEN=ghp_xxx USER_NAME=daniel-fbo python scripts/update_stats.py

No GitHub Actions o GH_TOKEN vem de um secret (ver SETUP.md).

NOTA sobre os números:
  - "repositórios" conta TODOS os repos onde você é owner, inclusive
    privados (o token enxerga o que a página pública deslogada não vê).
  - "estrelas" soma só estrelas de repositórios que você possui
    (ownerAffiliations: [OWNER]) — repositórios de organização (ex:
    projetos de grupo da faculdade) NÃO entram aqui, mesmo que você seja
    colaborador; eles aparecem em "contribuiu em X repositórios".
"""

import os
import re
import sys
import json
import time
import datetime
import pathlib

import requests

# ──────────────────────────────────────────────────────────────────────────
# Configuração
# ──────────────────────────────────────────────────────────────────────────

USER = os.environ.get("USER_NAME", "daniel-fbo")
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")

# >>> AJUSTE AQUI: sua data de nascimento (ano, mês, dia) <<<
BIRTHDAY = datetime.date(2007, 7, 1)

README = pathlib.Path("README.md")
CACHE = pathlib.Path("cache/loc_cache.json")
API = "https://api.github.com/graphql"

MAX_RETRIES = 3
RETRY_BASE_DELAY = 2  # segundos; backoff exponencial: 2, 4, 8...

if not TOKEN:
    sys.exit("ERRO: defina GH_TOKEN (ou GITHUB_TOKEN) no ambiente.")

HEADERS = {"Authorization": f"bearer {TOKEN}"}


def log(msg):
    """Log simples pro stderr — aparece no output do GitHub Actions."""
    print(msg, file=sys.stderr, flush=True)


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────

def gql(query, variables=None):
    """Executa uma query GraphQL com retry/backoff e devolve o nó `data`."""
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
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
        except Exception as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                delay = RETRY_BASE_DELAY ** attempt
                log(f"  ⚠️  tentativa {attempt}/{MAX_RETRIES} falhou ({exc}); "
                    f"nova tentativa em {delay}s")
                time.sleep(delay)
    # esgotou as tentativas
    raise last_exc


def validate_token():
    """Confere se o token é válido e corresponde ao USER esperado.
    Falha rápido (sem gastar tempo com walk_repo) se algo estiver errado."""
    query = "query { viewer { login } }"
    try:
        data = gql(query)
    except Exception as exc:
        sys.exit(f"ERRO: token inválido ou expirado — {exc}")

    viewer_login = data["viewer"]["login"]
    if viewer_login.lower() != USER.lower():
        log(f"  ⚠️  aviso: token pertence a '{viewer_login}', "
            f"mas USER_NAME é '{USER}'. Repositórios privados de "
            f"'{USER}' podem não aparecer.")


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

def build_block(repos, commits, stars, contrib, add, dele, skipped):
    net = add - dele
    today = datetime.date.today().isoformat()
    lines = [
        "```console",
        "$ daniel.fbo --status",
        f"  repositórios ...... {repos}",
        f"  commits ........... {commits:,}".replace(",", "."),
        f"  estrelas .......... {stars}",
        f"  contribuiu em ..... {contrib} repositórios",
        f"  linhas de código .. {net:,}  (+{add:,} / -{dele:,})".replace(",", "."),
    ]
    if skipped:
        lines.append(
            f"  aviso .............. {len(skipped)} repositório(s) pulado(s) "
            f"por erro (ver logs do Actions)"
        )
    lines += [
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
    validate_token()

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
    skipped = []

    for full in sorted(scan):
        owner, name = full.split("/", 1)
        try:
            count = commit_count(owner, name, uid)
        except Exception as exc:
            log(f"  ⚠️  pulei {full} (falha ao contar commits): {exc}")
            skipped.append(full)
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
            except Exception as exc:
                if cached:
                    log(f"  ⚠️  {full}: falha ao atualizar histórico ({exc}); "
                        f"usando valores em cache")
                    c, a, d = cached["commits"], cached["add"], cached["del"]
                else:
                    log(f"  ⚠️  pulei {full} (falha ao ler histórico, sem "
                        f"cache anterior): {exc}")
                    skipped.append(full)
                    continue

        fresh[full] = {"commits": c, "add": a, "del": d}
        total_commits += c
        total_add += a
        total_del += d

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(fresh, indent=2))

    if skipped:
        log(f"\nResumo: {len(skipped)} repositório(s) pulado(s) nesta execução: "
            f"{', '.join(skipped)}")

    block = build_block(
        repos_count, total_commits, stars, contrib, total_add, total_del, skipped
    )
    new_text = replace_section(text, "status", block)

    if new_text != text:
        README.write_text(new_text, encoding="utf-8")
        print("README atualizado.")
    else:
        print("Nenhuma mudança no README.")

    # Se algum repo foi pulado, sinaliza no exit code (não falha o job,
    # mas fica registrado no log e pode ser usado por um step condicional
    # no workflow, ex: `if: steps.stats.outputs.skipped != '0'`).
    if skipped:
        log(f"::warning::{len(skipped)} repositório(s) pulado(s) ao atualizar métricas")


if __name__ == "__main__":
    main()
