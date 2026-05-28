# changewatch — CI/CD & Deployment Design

**Date:** 2026-05-13  
**Status:** Approved

## Scope

Set up a GitHub repository, local git hooks, GitHub Actions CI, and Kubernetes deployment using secrets managed outside the image.

## 1. Repository

- Public GitHub repo: `github.com/stevendejongnl/changewatch`
- Single branch: `main`
- `.gitignore` covers: `.venv/`, `__pycache__/`, `.coverage`, `.pytest_cache/`, `uv.lock` is committed, `k8s/secrets/*.yaml` with exception `!k8s/secrets/*.example.yaml`

## 2. Git Hooks

Shell scripts in `.hooks/` (tracked in git, executable). Installed via `make install-hooks` (symlinks into `.git/hooks/`).

| Hook | Command | Purpose |
|------|---------|---------|
| `pre-commit` | `uv run pytest --no-cov -x` | Fast fail-fast check before each commit |
| `pre-push` | `uv run pytest` | Full suite with 100% coverage — mirrors CI exactly |

## 3. GitHub Actions CI

File: `.github/workflows/ci.yml`

**Job: `test`** — runs on every push and pull request
1. `actions/checkout@v4`
2. `astral-sh/setup-uv@v4`
3. `uv sync`
4. `uv run playwright install chromium --with-deps`
5. `uv run pytest`

**Job: `build`** — runs on `main` only, after `test` passes
1. `docker/login-action@v3` with `registry: ghcr.io`, `username: ${{ github.actor }}`, `password: ${{ secrets.GITHUB_TOKEN }}`
2. `docker/build-push-action@v6` — push `ghcr.io/stevendejongnl/changewatch:latest` and `:sha-${{ github.sha }}`

No GitHub secrets require manual setup — `GITHUB_TOKEN` is injected automatically by GitHub Actions.

## 4. K8s Secrets Pattern

```
k8s/
  secrets/
    changewatch-secrets.example.yaml   # tracked, placeholder values
    ghcr-pull-secret.example.yaml      # tracked, only needed if image repo goes private
```

**Workflow for applying secrets:**
```bash
cp k8s/secrets/changewatch-secrets.example.yaml k8s/secrets/changewatch-secrets.yaml
# edit: fill INFLUXDB_TOKEN, INFLUXDB_ORG, APPRISE_URL_TELEGRAM, etc.
kubectl apply -f k8s/secrets/changewatch-secrets.yaml
```

The deployment references the secret via `envFrom.secretRef.name: changewatch-secrets`. Credentials are never in the image.

## 5. K8s Deployment Image

`k8s/deployment.yaml` uses `ghcr.io/stevendejongnl/changewatch:latest` with Keel polling annotation (`keel.sh/policy: force`, `keel.sh/trigger: poll`). Image is public on GHCR so no `imagePullSecrets` needed.

## Non-goals

- Staging environment
- Multi-platform image builds
- Helm chart
