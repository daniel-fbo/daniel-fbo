#!/usr/bin/env python3
"""
Calcula o percentual de linguagens que o usuário realmente escreveu,
somando linhas adicionadas (git log --numstat) em uma lista curada de
repositórios (próprios ou de terceiros), e atualiza:
  - assets/lang-stats-dark.svg
  - assets/lang-stats-light.svg
  - README.md (bloco entre os marcadores LANG-STATS)

Não depende de nenhuma API externa de terceiros. Só usa `git` (CLI) e a
biblioteca padrão do Python.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPOS_FILE = os.path.join(REPO_ROOT, "scripts", "repos.txt")
AUTHORS_FILE = os.path.join(REPO_ROOT, "scripts", "authors.txt")
CACHE_FILE = os.path.join(REPO_ROOT, "cache", "loc_cache.json")
ASSETS_DIR = os.path.join(REPO_ROOT, "assets")
README_FILE = os.path.join(REPO_ROOT, "README.md")

TOP_N = 8
MARKER_START = "<!--LANG-STATS:START-->"
MARKER_END = "<!--LANG-STATS:END-->"

GH_TOKEN = os.environ.get("GH_TOKEN", "")
USER_NAME = os.environ.get("USER_NAME", "")

# Extensão -> linguagem. Só extensões de código de verdade; arquivos de
# config/dados/docs são ignorados de propósito (não contam como "linguagem escrita").
EXT_TO_LANG = {
    ".py": "Python",
    ".ipynb": "Jupyter Notebook",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".hpp": "C++",
    ".cs": "C#",
    ".go": "Go",
    ".rb": "Ruby",
    ".php": "PHP",
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sass": "Sass",
    ".sh": "Shell",
    ".bash": "Shell",
    ".sql": "SQL",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".swift": "Swift",
    ".rs": "Rust",
    ".dart": "Dart",
    ".r": "R",
    ".m": "Objective-C",
    ".lua": "Lua",
    ".pl": "Perl",
    ".scala": "Scala",
    ".hs": "Haskell",
    ".ex": "Elixir",
    ".exs": "Elixir",
    ".clj": "Clojure",
    ".vue": "Vue",
    ".jl": "Julia",
    ".erl": "Erlang",
}

# Cores aproximadas do GitHub Linguist, pra manter familiaridade visual.
LANG_COLORS = {
    "Python": "#3572A5",
    "Jupyter Notebook": "#DA5B0B",
    "JavaScript": "#f1e05a",
    "TypeScript": "#3178c6",
    "Java": "#b07219",
    "C": "#555555",
    "C++": "#f34b7d",
    "C#": "#178600",
    "Go": "#00ADD8",
    "Ruby": "#701516",
    "PHP": "#4F5D95",
    "HTML": "#e34c26",
    "CSS": "#563d7c",
    "SCSS": "#c6538c",
    "Sass": "#a53b70",
    "Shell": "#89e051",
    "SQL": "#e38c00",
    "Kotlin": "#A97BFF",
    "Swift": "#F05138",
    "Rust": "#dea584",
    "Dart": "#00B4AB",
    "R": "#198CE7",
    "Objective-C": "#438eff",
    "Lua": "#000080",
    "Perl": "#0298c3",
    "Scala": "#c22d40",
    "Haskell": "#5e5086",
    "Elixir": "#6e4a7e",
    "Clojure": "#db5855",
    "Vue": "#41b883",
    "Julia": "#a270ba",
    "Erlang": "#B83998",
}
DEFAULT_COLOR = "#d4af37"


def run(cmd, cwd=None):
    result = subprocess.run(
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    return result.returncode, result.stdout, result.stderr


def load_list(path):
    if not os.path.exists(path):
        return []
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                items.append(line)
    return items


def clone_repo(owner_repo, dest_dir):
    if GH_TOKEN:
        url = f"https://x-access-token:{GH_TOKEN}@github.com/{owner_repo}.git"
    else:
        url = f"https://github.com/{owner_repo}.git"
    code, out, err = run(["git", "clone", "--quiet", url, dest_dir])
    if code != 0:
        print(f"  [aviso] falha ao clonar {owner_repo}: {err.strip()}", file=sys.stderr)
        return False
    return True


def author_regex(patterns):
    escaped = [re.escape(p) for p in patterns if p.strip()]
    if not escaped:
        return None
    return re.compile("|".join(escaped), re.IGNORECASE)


def analyze_repo(repo_dir, author_re):
    """Retorna (commits, add, del, {linguagem: linhas_adicionadas})."""
    code, out, err = run(
        [
            "git",
            "log",
            "--no-merges",
            "--pretty=format:@@%H|%an|%ae",
            "--numstat",
        ],
        cwd=repo_dir,
    )
    if code != 0:
        print(f"  [aviso] git log falhou: {err.strip()}", file=sys.stderr)
        return 0, 0, 0, {}

    commits = 0
    total_add = 0
    total_del = 0
    lang_add = {}
    counting = False

    for line in out.splitlines():
        if line.startswith("@@"):
            _, an, ae = line[2:].split("|", 2)
            counting = bool(author_re.search(an) or author_re.search(ae))
            if counting:
                commits += 1
            continue
        if not counting or not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        add_s, del_s, path = parts
        if add_s == "-" or del_s == "-":
            continue  # arquivo binário
        add_n, del_n = int(add_s), int(del_s)
        total_add += add_n
        total_del += del_n
        ext = os.path.splitext(path)[1].lower()
        lang = EXT_TO_LANG.get(ext)
        if lang:
            lang_add[lang] = lang_add.get(lang, 0) + add_n

    return commits, total_add, total_del, lang_add


def build_svg(lang_percentages, title_color, text_color):
    row_h = 30
    width = 300
    height = 40 + row_h * len(lang_percentages)
    rows = []
    y = 40
    for lang, pct in lang_percentages:
        color = LANG_COLORS.get(lang, DEFAULT_COLOR)
        bar_w = max(2, int(pct / 100 * 160))
        rows.append(f"""
  <text x="0" y="{y - 6}" font-size="12" fill="{text_color}" font-family="'Segoe UI', Ubuntu, sans-serif">{lang}</text>
  <text x="290" y="{y - 6}" font-size="12" fill="{text_color}" font-family="'Segoe UI', Ubuntu, sans-serif" text-anchor="end">{pct:.1f}%</text>
  <rect x="0" y="{y}" width="160" height="6" rx="3" fill="{text_color}" opacity="0.15" />
  <rect x="0" y="{y}" width="{bar_w}" height="6" rx="3" fill="{color}" />
""")
        y += row_h

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <style>
    text {{ font-family: 'Segoe UI', Ubuntu, sans-serif; }}
  </style>
  <text x="0" y="20" font-size="16" font-weight="600" fill="{title_color}">Linguagens mais usadas</text>
  <g transform="translate(10, 0)">
    {''.join(rows)}
  </g>
</svg>"""
    return svg


def update_readme(timestamp):
    if not os.path.exists(README_FILE):
        print("  [aviso] README.md não encontrado, pulando atualização do README.")
        return
    with open(README_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    block = f"""{MARKER_START}
<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/{USER_NAME}/{USER_NAME}/main/assets/lang-stats-dark.svg?v={timestamp}" />
  <img src="https://raw.githubusercontent.com/{USER_NAME}/{USER_NAME}/main/assets/lang-stats-light.svg?v={timestamp}" height="220" alt="top languages" />
</picture>

</div>
{MARKER_END}"""

    if MARKER_START in content and MARKER_END in content:
        pattern = re.compile(
            re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END), re.DOTALL
        )
        content = pattern.sub(block, content)
    else:
        content = content.rstrip() + "\n\n" + block + "\n"

    with open(README_FILE, "w", encoding="utf-8") as f:
        f.write(content)


def main():
    if not USER_NAME:
        print("USER_NAME não definido.", file=sys.stderr)
        sys.exit(1)

    repos = load_list(REPOS_FILE)
    author_patterns = load_list(AUTHORS_FILE)
    author_re = author_regex(author_patterns)
    if not repos or not author_re:
        print("Configure scripts/repos.txt e scripts/authors.txt antes de rodar.", file=sys.stderr)
        sys.exit(1)

    per_repo = {}
    total_lang_add = {}

    with tempfile.TemporaryDirectory() as tmp:
        for owner_repo in repos:
            print(f"Analisando {owner_repo}...")
            dest = os.path.join(tmp, owner_repo.replace("/", "__"))
            if not clone_repo(owner_repo, dest):
                continue
            commits, add, dele, lang_add = analyze_repo(dest, author_re)
            per_repo[owner_repo] = {
                "commits": commits,
                "add": add,
                "del": dele,
                "languages": lang_add,
            }
            for lang, n in lang_add.items():
                total_lang_add[lang] = total_lang_add.get(lang, 0) + n

    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"updated_at": int(time.time()), "repos": per_repo},
            f,
            indent=2,
            ensure_ascii=False,
        )

    total = sum(total_lang_add.values())
    if total == 0:
        print("Nenhuma linha atribuída ao autor foi encontrada. Confira scripts/authors.txt.", file=sys.stderr)
        sys.exit(1)

    ranked = sorted(total_lang_add.items(), key=lambda kv: kv[1], reverse=True)[:TOP_N]
    percentages = [(lang, n / total * 100) for lang, n in ranked]

    os.makedirs(ASSETS_DIR, exist_ok=True)
    dark_svg = build_svg(percentages, title_color="#d4af37", text_color="#9ba3af")
    light_svg = build_svg(percentages, title_color="#8a6d1b", text_color="#4b5563")

    with open(os.path.join(ASSETS_DIR, "lang-stats-dark.svg"), "w", encoding="utf-8") as f:
        f.write(dark_svg)
    with open(os.path.join(ASSETS_DIR, "lang-stats-light.svg"), "w", encoding="utf-8") as f:
        f.write(light_svg)

    update_readme(timestamp=int(time.time()))

    print("\nResultado:")
    for lang, pct in percentages:
        print(f"  {lang:<18} {pct:5.1f}%")


if __name__ == "__main__":
    main()
