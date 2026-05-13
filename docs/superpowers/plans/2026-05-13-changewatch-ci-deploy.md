# changewatch CI/CD & Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship changewatch as a GitHub repo with GHCR image CI/CD, local pre-commit/pre-push hooks, and Kubernetes manifests that load all credentials from a Secret — never from the image.

**Architecture:** GitHub Actions tests on every push, builds and pushes `ghcr.io/stevendejongnl/changewatch:latest` on `main`. Local hooks replicate CI checks locally. K8s deployment pulls from GHCR (public image, no pull secret needed) and injects credentials at runtime via `envFrom.secretRef`.

**Tech Stack:** Python/uv, pytest, Playwright, Docker/GHCR, GitHub Actions, Kubernetes, Keel

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `.gitignore` | Create | Excludes build artifacts and real secret files |
| `.dockerignore` | Create | Keeps image lean (no tests/docs in image) |
| `Makefile` | Create | `make install-hooks` wires `.hooks/` into `.git/hooks/` |
| `.hooks/pre-commit` | Create | Fast local check before each commit |
| `.hooks/pre-push` | Create | Full coverage check before push (mirrors CI) |
| `.github/workflows/ci.yml` | Create | Test + build + push to GHCR |
| `k8s/secrets/changewatch-secrets.example.yaml` | Create | Template for the runtime credentials secret |
| `k8s/secrets/ghcr-pull-secret.example.yaml` | Create | Template for GHCR pull secret (needed only if image goes private) |
| `k8s/secret.example.yaml` | Delete | Superseded by `k8s/secrets/` structure |
| `k8s/deployment.yaml` | Modify | Change image from Gitea registry to GHCR |

---

### Task 1: Initialize git repo and .gitignore

**Files:**
- Create: `.gitignore`
- Create: `.dockerignore`

- [ ] **Step 1: Init git repo**

```bash
cd /home/stevendejong/workspace/personal/changewatch
git init
git checkout -b main
```

Expected: `Initialized empty Git repository in .../changewatch/.git/`

- [ ] **Step 2: Create .gitignore**

Create `/home/stevendejong/workspace/personal/changewatch/.gitignore`:

```gitignore
# Python
__pycache__/
*.pyc
.venv/
.coverage
.pytest_cache/

# Docs/specs build artifacts
docs/superpowers/plans/*.md.bak

# K8s real secret files — examples are tracked, real values are not
k8s/secrets/*.yaml
!k8s/secrets/*.example.yaml

# Editor
.idea/
.vscode/
*.swp
```

- [ ] **Step 3: Create .dockerignore**

Create `/home/stevendejong/workspace/personal/changewatch/.dockerignore`:

```dockerignore
.git/
.venv/
.hooks/
.github/
docs/
app/*_test.py
app/conftest.py
app/templates/
app/static/
__pycache__/
.coverage
.pytest_cache/
*.md
Makefile
```

- [ ] **Step 4: Initial commit**

```bash
cd /home/stevendejong/workspace/personal/changewatch
git add .
git commit -m "chore: initial commit — changewatch app with 100% test coverage"
```

Expected: commit hash printed, summary showing added files.

---

### Task 2: Git hooks and Makefile

**Files:**
- Create: `.hooks/pre-commit`
- Create: `.hooks/pre-push`
- Create: `Makefile`

- [ ] **Step 1: Create .hooks/pre-commit**

Create `/home/stevendejong/workspace/personal/changewatch/.hooks/pre-commit`:

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "▶ pre-commit: running tests (fail-fast, no coverage)..."
cd "$(git rev-parse --show-toplevel)"
uv run pytest --no-cov -x -q

echo "✓ pre-commit passed"
```

- [ ] **Step 2: Create .hooks/pre-push**

Create `/home/stevendejong/workspace/personal/changewatch/.hooks/pre-push`:

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "▶ pre-push: running full test suite with coverage check..."
cd "$(git rev-parse --show-toplevel)"
uv run pytest

echo "✓ pre-push passed — safe to push"
```

- [ ] **Step 3: Make hooks executable**

```bash
chmod +x /home/stevendejong/workspace/personal/changewatch/.hooks/pre-commit
chmod +x /home/stevendejong/workspace/personal/changewatch/.hooks/pre-push
```

- [ ] **Step 4: Create Makefile**

Create `/home/stevendejong/workspace/personal/changewatch/Makefile`:

```makefile
.PHONY: install-hooks test

install-hooks:
	ln -sf ../../.hooks/pre-commit .git/hooks/pre-commit
	ln -sf ../../.hooks/pre-push .git/hooks/pre-push
	@echo "Hooks installed. Run 'make test' to verify."

test:
	uv run pytest
```

- [ ] **Step 5: Install hooks locally**

```bash
cd /home/stevendejong/workspace/personal/changewatch
make install-hooks
```

Expected:
```
Hooks installed. Run 'make test' to verify.
```

- [ ] **Step 6: Verify pre-commit hook fires correctly**

```bash
cd /home/stevendejong/workspace/personal/changewatch
touch /tmp/dummy_test_file && git add /tmp/dummy_test_file 2>/dev/null || true
git stash 2>/dev/null || true
.git/hooks/pre-commit
```

Expected: tests run and pass (51 passed).

- [ ] **Step 7: Commit hooks and Makefile**

```bash
cd /home/stevendejong/workspace/personal/changewatch
git add .hooks/ Makefile
git commit -m "chore: add pre-commit and pre-push hooks with install-hooks make target"
```

---

### Task 3: GitHub Actions CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create workflow directory**

```bash
mkdir -p /home/stevendejong/workspace/personal/changewatch/.github/workflows
```

- [ ] **Step 2: Create ci.yml**

Create `/home/stevendejong/workspace/personal/changewatch/.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: ["main"]
  pull_request:

jobs:
  test:
    name: Test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up uv
        uses: astral-sh/setup-uv@v4

      - name: Install dependencies
        run: uv sync

      - name: Install Chromium for Playwright
        run: uv run playwright install chromium --with-deps

      - name: Run tests
        run: uv run pytest

  build:
    name: Build & Push
    needs: test
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push
        uses: docker/build-push-action@v6
        with:
          context: .
          push: true
          tags: |
            ghcr.io/stevendejongnl/changewatch:latest
            ghcr.io/stevendejongnl/changewatch:sha-${{ github.sha }}
```

- [ ] **Step 3: Commit workflow**

```bash
cd /home/stevendejong/workspace/personal/changewatch
git add .github/
git commit -m "ci: add GitHub Actions test + build pipeline pushing to GHCR"
```

---

### Task 4: K8s secret templates and update deployment

**Files:**
- Create: `k8s/secrets/changewatch-secrets.example.yaml`
- Create: `k8s/secrets/ghcr-pull-secret.example.yaml`
- Delete: `k8s/secret.example.yaml`
- Modify: `k8s/deployment.yaml` (line 28 — image ref)

- [ ] **Step 1: Create secrets directory**

```bash
mkdir -p /home/stevendejong/workspace/personal/changewatch/k8s/secrets
```

- [ ] **Step 2: Create changewatch-secrets.example.yaml**

Create `/home/stevendejong/workspace/personal/changewatch/k8s/secrets/changewatch-secrets.example.yaml`:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: changewatch-secrets
  namespace: changewatch
type: Opaque
stringData:
  # Apprise notification channels — one env var per Apprise tag used in monitors
  # Tag name must match the tag passed to notify(tags=["telegram"]) in monitor scripts
  APPRISE_URL_TELEGRAM: "tgram://<bot_token>/<chat_id>"

  # InfluxDB (CT 125, 192.168.1.22:8086)
  INFLUXDB_URL: "http://192.168.1.22:8086"
  INFLUXDB_TOKEN: "<your-influxdb-token>"
  INFLUXDB_ORG: "<your-org-name>"
  INFLUXDB_BUCKET: "changewatch"
```

- [ ] **Step 3: Create ghcr-pull-secret.example.yaml**

Create `/home/stevendejong/workspace/personal/changewatch/k8s/secrets/ghcr-pull-secret.example.yaml`:

```yaml
# Only needed if the GHCR image is set to private.
# If the image is public (default for public repos), skip this file.
#
# To create a GHCR token:
#   1. GitHub → Settings → Developer settings → Personal access tokens → Fine-grained
#   2. Grant: read:packages
#   3. Base64 encode: echo -n "stevendejongnl:<token>" | base64
#
apiVersion: v1
kind: Secret
metadata:
  name: ghcr-pull-secret
  namespace: changewatch
type: kubernetes.io/dockerconfigjson
stringData:
  .dockerconfigjson: |
    {
      "auths": {
        "ghcr.io": {
          "username": "stevendejongnl",
          "password": "<your-ghcr-token>",
          "auth": "<base64-of-username:token>"
        }
      }
    }
---
# If using this secret, add to deployment.yaml under spec.template.spec:
#   imagePullSecrets:
#     - name: ghcr-pull-secret
```

- [ ] **Step 4: Update deployment.yaml image reference**

In `/home/stevendejong/workspace/personal/changewatch/k8s/deployment.yaml`, change line 28 from:

```yaml
          image: git.madebysteven.nl/stevendejong/changewatch:latest
```

to:

```yaml
          image: ghcr.io/stevendejongnl/changewatch:latest
```

- [ ] **Step 5: Remove superseded secret.example.yaml**

```bash
rm /home/stevendejong/workspace/personal/changewatch/k8s/secret.example.yaml
```

- [ ] **Step 6: Commit K8s changes**

```bash
cd /home/stevendejong/workspace/personal/changewatch
git add k8s/
git commit -m "feat(k8s): move secret templates to k8s/secrets/, point deployment at GHCR"
```

---

### Task 5: Create GitHub repo and push

**Prerequisites:** `gh` CLI authenticated (`gh auth status` shows logged in as `stevendejongnl`).

- [ ] **Step 1: Verify gh auth**

```bash
gh auth status
```

Expected: `Logged in to github.com as stevendejongnl`

- [ ] **Step 2: Create public GitHub repo**

```bash
cd /home/stevendejong/workspace/personal/changewatch
gh repo create stevendejongnl/changewatch \
  --public \
  --description "Code-defined change monitors with FastAPI + Playwright" \
  --source=. \
  --remote=origin \
  --push
```

Expected: repo URL printed, `main` branch pushed.

- [ ] **Step 3: Verify CI triggered**

```bash
gh run list --repo stevendejongnl/changewatch --limit 3
```

Expected: one run listed with status `queued` or `in_progress`.

- [ ] **Step 4: Watch CI run**

```bash
gh run watch --repo stevendejongnl/changewatch
```

Expected: `test` job passes, `build` job pushes image to GHCR.

- [ ] **Step 5: Verify image in GHCR**

```bash
gh api /users/stevendejongnl/packages?package_type=container \
  --jq '.[].name'
```

Expected: `changewatch` listed.

- [ ] **Step 6: Make GHCR image public (if not already)**

```bash
gh api --method PATCH \
  /user/packages/container/changewatch/versions \
  --field visibility=public 2>/dev/null || true
```

Or via browser: `https://github.com/users/stevendejongnl/packages/container/changewatch/settings` → Change visibility → Public.

---

## Apply to K8s (manual steps after CI succeeds)

These steps run on your local machine with `kubectl` pointed at the cluster.

```bash
cd /home/stevendejong/workspace/personal/changewatch

# 1. Create namespace
kubectl apply -f k8s/namespace.yaml

# 2. Apply secrets (copy example, fill real values first)
cp k8s/secrets/changewatch-secrets.example.yaml k8s/secrets/changewatch-secrets.yaml
# edit k8s/secrets/changewatch-secrets.yaml with real token values
kubectl apply -f k8s/secrets/changewatch-secrets.yaml

# 3. Apply storage
kubectl apply -f k8s/pv.yaml
kubectl apply -f k8s/pvc.yaml

# 4. Apply app
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/ingress.yaml

# 5. Verify
kubectl -n changewatch rollout status deployment/changewatch
kubectl -n changewatch get pods
```

---

## Self-Review

- **Spec coverage:** All 5 spec sections covered ✓  
- **Placeholders:** None — all commands, file contents, and YAML are complete ✓  
- **Consistency:** Image ref `ghcr.io/stevendejongnl/changewatch:latest` matches across `ci.yml`, `deployment.yaml`, and the GHCR API steps ✓  
- **Secret never in image:** `changewatch-secrets` is `envFrom` at runtime; Dockerfile has no ENV with credentials ✓
