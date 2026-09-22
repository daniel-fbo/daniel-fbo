# Setup

1. Crie um token clássico com os escopos `repo` e `read:user`.
2. Adicione-o como secret `GH_TOKEN` em Settings > Secrets and variables > Actions.
3. Em Actions, rode o workflow `profile stats` manualmente.

- `profile stats`: roda diariamente, atualiza o bloco `status` do README, `cache/loc_cache.json` e os SVGs de linguagens em `assets/`.
- `snake`: roda a cada 12h e publica a animação no branch `output`.

Execução local:

```sh
GH_TOKEN=$(gh auth token) python scripts/update_stats.py
```
