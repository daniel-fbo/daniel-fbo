# Setup — perfil dinâmico

Tudo isso vive em um repositório **especial** com o mesmo nome do seu usuário:
`daniel-fbo/daniel-fbo`. O `README.md` desse repo é o que aparece na sua página de perfil.

## 1. Criar o repositório de perfil

1. New repository → nome **exatamente** `daniel-fbo` → marque **Public** → **Add a README**.
2. O GitHub mostra um aviso ✨ "this is a special repository" — é esse mesmo.

## 2. Subir os arquivos

Copie para a raiz do repo, mantendo a estrutura:

```
daniel-fbo/
├── README.md
├── requirements.txt
├── scripts/
│   └── update_stats.py
├── cache/
│   └── loc_cache.json
└── .github/
    └── workflows/
        ├── profile-stats.yml
        └── snake.yml
```

## 3. Ajustar sua data de nascimento

Em `scripts/update_stats.py`, troque a linha:

```python
BIRTHDAY = datetime.date(2005, 1, 1)   # ano, mês, dia
```

## 4. Criar o token (necessário p/ linhas de código e repos privados)

O `GITHUB_TOKEN` padrão não enxerga o histórico completo nem repos privados, então:

1. Settings → Developer settings → **Personal access tokens → Tokens (classic)** → Generate new (classic).
2. Marque os escopos **`repo`** e **`read:user`**.
3. Copie o token.
4. No repo `daniel-fbo`: Settings → Secrets and variables → Actions → **New repository secret**
   - Name: `GH_TOKEN`
   - Value: o token.

> Sem repos privados/LOC, dá pra rodar só com o `GITHUB_TOKEN` padrão — mas aí as linhas de código contam só o que ele alcança.

## 5. Ligar e rodar

Actions → habilite os workflows → no **profile stats**, clique **Run workflow** pra forçar a primeira execução.
Depois disso ele roda sozinho todo dia e reescreve o bloco `status` do README.

## 6. Cobra (snake)

O workflow **snake** publica os SVGs no branch `output`. Roda automático; o README já aponta pra lá.
Na primeira vez pode levar um ou dois minutos pro branch `output` existir — até lá a imagem fica quebrada, é normal.

---

### Personalização rápida

- **Cor de destaque:** o dourado é `d4af37` (claro: `b8860b`). Procure e substitua nos arquivos pra trocar a paleta.
- **Frases do header:** edite o parâmetro `lines=...` do `readme-typing-svg` no `README.md`.
- **Cards de métrica** (github-readme-stats) usam a instância pública; se ficar lento/limitado, dá pra subir a sua própria (self-host) e trocar a URL.
