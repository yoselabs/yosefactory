# Jira Dispatcher (Mode 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Mode-1 (Jira + GitHub) runtime over Days 2–3 — a thin FastAPI dispatcher on Dokploy fronts Jira webhooks and triggers the same engine in GH Actions. The engine gains two additive adapters (one input, one output subscriber) and is ticket-system-agnostic; Jira lives only in the dispatcher.

**Architecture:** New `packages/dispatcher/` FastAPI service exposes three endpoints: `/jira/events` (webhook → `workflow_dispatch`), `/gh/events` (webhook → Jira transitions + unblock dependents), `/runs/{run_id}/events` (engine posts domain events; dispatcher translates → Jira comments/transitions). Engine adds `WorkflowInputReader` (input) and `DispatcherEventSubscriber` (output) that activate on `DISPATCHER_URL` env. Capability tokens are per-run HMAC, 24h. One Docker image per package; deployed via Dokploy compose with Traefik TLS.

**Tech Stack:** FastAPI + Pydantic v2 (dispatcher), httpx (engine → dispatcher + dispatcher → Jira/GH), atlassian-python-api (Jira REST), PyJWT/cryptography (GH App JWT for workflow_dispatch), hmac/hashlib (capability tokens + webhook sig verification), pytest (existing), Docker + Traefik labels (Dokploy).

**Hard prerequisites:**
1. Plan A (`docs/superpowers/plans/2026-04-19-gh-native-runtime.md`) merged to main.
2. Plan A's **Phase 0 (uv workspace refactor) MUST be done**, not skipped. If it was skipped, do it as Task 0.1 of this plan before anything else.
3. A Dokploy instance reachable via Traefik with a wildcard DNS record (already in place per `k-my:deployment-platform` setup).
4. A GitHub App registered in the yoselabs org with `contents: write`, `issues: read`, `pull_requests: write`, `actions: write` permissions, installed on target repos. Record the App ID and private key.
5. Jira Cloud instance with bot user, API token generated, webhook permission available.

---

## Phase boundaries

- **Phase 0:** Ensure workspace layout, create branch, scaffold `packages/dispatcher/`.
- **Phase 1:** Domain event wire contract + capability tokens + config loading.
- **Phase 2:** Jira adapter (dispatcher-side) — Jira REST calls, event translation.
- **Phase 3:** Webhook routes (Jira + GH) — signature verification, business logic.
- **Phase 4:** Engine additions — `WorkflowInputReader`, `DispatcherEventSubscriber`, composition wiring.
- **Phase 5:** Reusable workflow + target-repo example.
- **Phase 6:** Shaping skill (Jira mode).
- **Phase 7:** Dockerfiles + Dokploy compose + deploy.
- **Phase 8:** End-to-end smoke test + docs.

Stop between phases, `make check`, commit. Frequent commits.

---

## Task 0: Branch + workspace prerequisites

### Task 0.1 (CONDITIONAL): uv workspace refactor if skipped in Plan A

Execute only if `packages/engine/` does not exist in the repo. Otherwise skip.

**Files:**
- Restructure: `src/a2sdlc/**` → `packages/engine/src/a2sdlc/**`
- Create: `packages/engine/pyproject.toml`
- Modify: root `pyproject.toml`

- [ ] **Step 1: Check state**

```bash
test -d packages/engine && echo "SKIP — workspace already done" || echo "RUN — workspace refactor needed"
```

If `SKIP`: proceed to Task 0.2. If `RUN`: execute Plan A's Phase 0 tasks 0.1 and 0.2 verbatim (copy the task content from `docs/superpowers/plans/2026-04-19-gh-native-runtime.md` Task 0.1, 0.2), then return here.

- [ ] **Step 2: `make check` + commit**

```bash
make check
git add -A
git commit -m "refactor: move engine into uv workspace member packages/engine (carry-over from Plan A)"
```

### Task 0.2: Create feature branch

**Files:** No files.

- [ ] **Step 1: Cut a branch off main**

```bash
cd /Users/iorlas/Workspaces/a2sdlc-engine
git fetch origin
git checkout main
git pull --ff-only
git checkout -b feat/jira-dispatcher
git status
```

Expected: `nothing to commit, working tree clean`.

### Task 0.3: Scaffold `packages/dispatcher/`

**Files:**
- Create: `packages/dispatcher/pyproject.toml`
- Create: `packages/dispatcher/src/a2sdlc_dispatcher/__init__.py`
- Create: `packages/dispatcher/src/a2sdlc_dispatcher/server.py`
- Create: `packages/dispatcher/src/a2sdlc_dispatcher/_version.py`

- [ ] **Step 1: Write `packages/dispatcher/pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "a2sdlc-dispatcher"
version = "0.1.0"
description = "a2sdlc dispatcher — FastAPI service fronting Jira and triggering engine runs in GH Actions."
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "httpx>=0.27",
    "pydantic>=2.8",
    "pydantic-settings>=2.4",
    "atlassian-python-api>=3.41",
    "pyjwt[crypto]>=2.9",
    "python-ulid>=2.0",
]

[project.scripts]
a2sdlc-dispatcher = "a2sdlc_dispatcher.server:run"

[tool.hatch.build.targets.wheel]
packages = ["src/a2sdlc_dispatcher"]
```

- [ ] **Step 2: Write `packages/dispatcher/src/a2sdlc_dispatcher/__init__.py`**

```python
"""a2sdlc-dispatcher — FastAPI service."""
from a2sdlc_dispatcher._version import __version__

__all__ = ["__version__"]
```

- [ ] **Step 3: Write `packages/dispatcher/src/a2sdlc_dispatcher/_version.py`**

```python
__version__ = "0.1.0"
```

- [ ] **Step 4: Write minimal `packages/dispatcher/src/a2sdlc_dispatcher/server.py`**

```python
"""FastAPI app entry point."""
from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="a2sdlc-dispatcher", version="0.1.0")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


def run() -> None:
    """Run the service via uvicorn — used by the `a2sdlc-dispatcher` script."""
    import uvicorn

    uvicorn.run("a2sdlc_dispatcher.server:app", host="0.0.0.0", port=8000, log_level="info")
```

- [ ] **Step 5: Sync and verify it starts**

```bash
uv sync --all-packages
uv run --package a2sdlc-dispatcher python -c "from a2sdlc_dispatcher.server import app; print(app.title)"
```

Expected: `a2sdlc-dispatcher`.

- [ ] **Step 6: Commit**

```bash
git add packages/dispatcher/
git commit -m "feat(dispatcher): scaffold packages/dispatcher with FastAPI healthz"
```

---

## Phase 1: Domain events, HMAC tokens, config

### Task 1.1: Domain event Pydantic models

**Files:**
- Create: `packages/dispatcher/src/a2sdlc_dispatcher/domain_events.py`
- Test: `packages/dispatcher/tests/test_domain_events.py`

- [ ] **Step 1: Write failing test**

```python
# packages/dispatcher/tests/test_domain_events.py
import pytest
from pydantic import ValidationError
from a2sdlc_dispatcher.domain_events import DomainEventAdapter


def test_parse_run_started():
    data = {"kind": "run_started", "run_id": "abc", "mlflow_url": "https://m/r/1"}
    evt = DomainEventAdapter.validate_python(data)
    assert evt.kind == "run_started"
    assert evt.run_id == "abc"
    assert evt.mlflow_url == "https://m/r/1"


def test_parse_stage_started():
    evt = DomainEventAdapter.validate_python({"kind": "stage_started", "stage": "implement"})
    assert evt.kind == "stage_started"
    assert evt.stage == "implement"


def test_parse_pr_opened():
    evt = DomainEventAdapter.validate_python(
        {"kind": "pr_opened", "url": "https://github.com/x/y/pull/1", "base": "main", "head": "x/y"}
    )
    assert evt.kind == "pr_opened"
    assert evt.base == "main"


def test_parse_run_failed():
    evt = DomainEventAdapter.validate_python({"kind": "run_failed", "error": "boom"})
    assert evt.kind == "run_failed"
    assert evt.error == "boom"


def test_parse_unknown_kind_is_accepted_as_raw():
    evt = DomainEventAdapter.validate_python({"kind": "future_event_v2", "foo": "bar"})
    # Unknown kind is accepted silently via the discriminated-union fallback,
    # for forward compatibility (engine may emit new kinds ahead of dispatcher).
    assert evt.kind == "future_event_v2"


def test_parse_missing_kind_raises():
    with pytest.raises(ValidationError):
        DomainEventAdapter.validate_python({"run_id": "abc"})
```

- [ ] **Step 2: Run — expect FAIL (module missing)**

```bash
uv run --package a2sdlc-dispatcher pytest packages/dispatcher/tests/test_domain_events.py -v
```

Expected: FAIL with import error.

- [ ] **Step 3: Implement `domain_events.py`**

```python
"""Wire-format Pydantic models for engine → dispatcher domain events.

Known event kinds are decoded into typed models. Unknown kinds are accepted
as a forward-compat fallback so the engine can emit new kinds ahead of
dispatcher awareness without breaking ingestion.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter


class RunStarted(BaseModel):
    kind: Literal["run_started"] = "run_started"
    run_id: str
    mlflow_url: str | None = None


class StageStarted(BaseModel):
    kind: Literal["stage_started"] = "stage_started"
    stage: str


class StageCompleted(BaseModel):
    kind: Literal["stage_completed"] = "stage_completed"
    stage: str
    ok: bool
    summary: str | None = None


class PROpened(BaseModel):
    kind: Literal["pr_opened"] = "pr_opened"
    url: str
    base: str
    head: str


class PRUpdated(BaseModel):
    kind: Literal["pr_updated"] = "pr_updated"
    url: str
    update_kind: Literal["ci-green", "changes-requested", "approved"]


class RunCompleted(BaseModel):
    kind: Literal["run_completed"] = "run_completed"
    pr_url: str | None = None
    outcome: Literal["awaiting_merge", "merged", "failed"]


class RunFailed(BaseModel):
    kind: Literal["run_failed"] = "run_failed"
    error: str
    mlflow_url: str | None = None


class UnknownEvent(BaseModel):
    """Forward-compat — any kind we don't explicitly model."""

    model_config = {"extra": "allow"}
    kind: str


KnownEvent = Annotated[
    RunStarted | StageStarted | StageCompleted | PROpened | PRUpdated | RunCompleted | RunFailed,
    Field(discriminator="kind"),
]


def _validate(data: dict):
    known_kinds = {"run_started", "stage_started", "stage_completed", "pr_opened", "pr_updated", "run_completed", "run_failed"}
    k = data.get("kind")
    if k in known_kinds:
        return TypeAdapter(KnownEvent).validate_python(data)
    if k is None:
        raise ValueError("missing 'kind' field")
    return UnknownEvent.model_validate(data)


class _Adapter:
    """Callable wrapper exposing validate_python like a TypeAdapter."""

    @staticmethod
    def validate_python(data: dict):
        return _validate(data)


DomainEventAdapter = _Adapter()
```

- [ ] **Step 4: Run — expect PASS**

```bash
uv run --package a2sdlc-dispatcher pytest packages/dispatcher/tests/test_domain_events.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/dispatcher/src/a2sdlc_dispatcher/domain_events.py packages/dispatcher/tests/test_domain_events.py
git commit -m "feat(dispatcher): domain event Pydantic models with forward-compat"
```

### Task 1.2: HMAC capability tokens

**Files:**
- Create: `packages/dispatcher/src/a2sdlc_dispatcher/hmac_token.py`
- Test: `packages/dispatcher/tests/test_hmac_token.py`

- [ ] **Step 1: Write failing test**

```python
# packages/dispatcher/tests/test_hmac_token.py
import time
import pytest
from a2sdlc_dispatcher.hmac_token import mint_token, verify_token, TokenError

KEY = b"test-signing-key-32-bytes-long___"


def test_mint_then_verify_succeeds():
    token = mint_token("run-123", "A2X-42", key=KEY, ttl_seconds=60)
    claims = verify_token(token, key=KEY)
    assert claims.run_id == "run-123"
    assert claims.ticket_key == "A2X-42"


def test_expired_token_rejected():
    token = mint_token("run-123", "A2X-42", key=KEY, ttl_seconds=-1)
    with pytest.raises(TokenError, match="expired"):
        verify_token(token, key=KEY)


def test_tampered_signature_rejected():
    token = mint_token("run-123", "A2X-42", key=KEY, ttl_seconds=60)
    bad = token[:-4] + "XXXX"
    with pytest.raises(TokenError, match="signature"):
        verify_token(bad, key=KEY)


def test_wrong_key_rejected():
    token = mint_token("run-123", "A2X-42", key=KEY, ttl_seconds=60)
    with pytest.raises(TokenError):
        verify_token(token, key=b"different-key-also-32-bytes-long_")
```

- [ ] **Step 2: Run — expect FAIL**

```bash
uv run --package a2sdlc-dispatcher pytest packages/dispatcher/tests/test_hmac_token.py -v
```

Expected: FAIL (import error).

- [ ] **Step 3: Implement `hmac_token.py`**

```python
"""Per-run HMAC capability tokens.

Token format: base64url(payload || "|" || sig)
  payload = run_id || "|" || ticket_key || "|" || exp
  sig     = HMAC-SHA256(key, payload).hexdigest()

Scope: single run, single 24h window (configurable per mint). Cannot be
replayed for other tickets and cannot be refreshed — mint a fresh one.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass


class TokenError(Exception):
    """Raised on any verification failure (signature, expiry, format)."""


@dataclass(frozen=True)
class TokenClaims:
    run_id: str
    ticket_key: str
    exp: int


def _sign(payload: str, key: bytes) -> str:
    return hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def mint_token(run_id: str, ticket_key: str, *, key: bytes, ttl_seconds: int = 86400) -> str:
    exp = int(time.time()) + ttl_seconds
    payload = f"{run_id}|{ticket_key}|{exp}"
    sig = _sign(payload, key)
    raw = f"{payload}|{sig}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def verify_token(token: str, *, key: bytes) -> TokenClaims:
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except Exception as e:
        raise TokenError(f"malformed token: {e}") from None
    parts = raw.split("|")
    if len(parts) != 4:
        raise TokenError("malformed payload")
    run_id, ticket_key, exp_s, sig = parts
    payload = f"{run_id}|{ticket_key}|{exp_s}"
    expected = _sign(payload, key)
    if not hmac.compare_digest(sig, expected):
        raise TokenError("bad signature")
    try:
        exp = int(exp_s)
    except ValueError:
        raise TokenError("bad expiry") from None
    if exp < int(time.time()):
        raise TokenError("expired")
    return TokenClaims(run_id=run_id, ticket_key=ticket_key, exp=exp)
```

- [ ] **Step 4: Run — expect PASS**

```bash
uv run --package a2sdlc-dispatcher pytest packages/dispatcher/tests/test_hmac_token.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/dispatcher/src/a2sdlc_dispatcher/hmac_token.py packages/dispatcher/tests/test_hmac_token.py
git commit -m "feat(dispatcher): HMAC capability tokens for per-run event ingest"
```

### Task 1.3: Settings via pydantic-settings + PROJECTS_JSON

**Files:**
- Create: `packages/dispatcher/src/a2sdlc_dispatcher/settings.py`
- Test: `packages/dispatcher/tests/test_settings.py`

- [ ] **Step 1: Write failing test**

```python
# packages/dispatcher/tests/test_settings.py
import json
import pytest
from a2sdlc_dispatcher.settings import Settings


PROJECTS = json.dumps([
    {
        "jira_key": "A2X",
        "repo": "acme/webapp",
        "default_base": "main",
    },
    {
        "jira_key": "BILL",
        "repo": "acme/billing",
        "status_ready": "Backlog → Ready",
    },
])


def test_loads_required_fields(monkeypatch):
    monkeypatch.setenv("PROJECTS_JSON", PROJECTS)
    monkeypatch.setenv("JIRA_BASE_URL", "https://acme.atlassian.net")
    monkeypatch.setenv("JIRA_USER", "bot@acme.com")
    monkeypatch.setenv("JIRA_TOKEN", "x")
    monkeypatch.setenv("GH_APP_ID", "12345")
    monkeypatch.setenv("GH_APP_PRIVATE_KEY", "dummy-pem")
    monkeypatch.setenv("GH_APP_INSTALLATION_ID", "99")
    monkeypatch.setenv("HMAC_SIGNING_KEY", "k" * 32)

    s = Settings()
    assert len(s.projects) == 2
    assert s.project_by_key("A2X").repo == "acme/webapp"
    assert s.project_by_key("BILL").status_ready == "Backlog → Ready"
    # defaults applied
    assert s.project_by_key("A2X").status_ready == "Ready"


def test_missing_required_raises(monkeypatch):
    monkeypatch.delenv("JIRA_BASE_URL", raising=False)
    with pytest.raises(Exception):
        Settings()


def test_unknown_project_key(monkeypatch):
    monkeypatch.setenv("PROJECTS_JSON", PROJECTS)
    monkeypatch.setenv("JIRA_BASE_URL", "https://acme.atlassian.net")
    monkeypatch.setenv("JIRA_USER", "bot@acme.com")
    monkeypatch.setenv("JIRA_TOKEN", "x")
    monkeypatch.setenv("GH_APP_ID", "12345")
    monkeypatch.setenv("GH_APP_PRIVATE_KEY", "dummy-pem")
    monkeypatch.setenv("GH_APP_INSTALLATION_ID", "99")
    monkeypatch.setenv("HMAC_SIGNING_KEY", "k" * 32)

    s = Settings()
    with pytest.raises(KeyError):
        s.project_by_key("UNKNOWN")
```

- [ ] **Step 2: Run — expect FAIL**

```bash
uv run --package a2sdlc-dispatcher pytest packages/dispatcher/tests/test_settings.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `settings.py`**

```python
"""Dispatcher config — env-driven via pydantic-settings.

Projects come from a JSON array in PROJECTS_JSON. Secrets come from env.
"""
from __future__ import annotations

import json
from typing import Self

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProjectConfig(BaseModel):
    jira_key: str
    repo: str
    default_base: str = "main"
    status_ready: str = "Ready"
    status_in_progress: str = "In Progress"
    status_review: str = "In Review"
    status_done: str = "Done"
    status_blocked: str = "Blocked"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    projects: list[ProjectConfig] = Field(default_factory=list)

    jira_base_url: str
    jira_user: str
    jira_token: SecretStr

    gh_app_id: int
    gh_app_private_key: SecretStr

    hmac_signing_key: SecretStr

    jira_webhook_secret: SecretStr | None = None
    gh_webhook_secret: SecretStr | None = None
    dokploy_deploy_token: SecretStr | None = None

    # Public URL the dispatcher is reachable at (what engine runs in CI call).
    # Set in Dokploy env to e.g. "https://dispatcher.yose.tld". Prefer this
    # over reading request.base_url so TLS/host rewriting via Traefik can't mislead us.
    self_url: str = ""

    # GH App installation id — for JWT-based token refresh instead of long-lived PAT.
    gh_app_installation_id: int = 0

    @field_validator("projects", mode="before")
    @classmethod
    def _load_projects(cls, v):
        if isinstance(v, str):
            return json.loads(v)
        return v

    def project_by_key(self, key: str) -> ProjectConfig:
        for p in self.projects:
            if p.jira_key == key:
                return p
        raise KeyError(f"no project with jira_key={key!r}")
```

The `projects` field auto-loads from `PROJECTS_JSON` because pydantic-settings reads uppercased field names by default — but `projects` → `PROJECTS` would collide with `PROJECTS_JSON`. Add an explicit alias:

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    projects: list[ProjectConfig] = Field(default_factory=list, alias="PROJECTS_JSON")
    # ...rest unchanged
```

- [ ] **Step 4: Run — expect PASS**

```bash
uv run --package a2sdlc-dispatcher pytest packages/dispatcher/tests/test_settings.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/dispatcher/src/a2sdlc_dispatcher/settings.py packages/dispatcher/tests/test_settings.py
git commit -m "feat(dispatcher): Settings + ProjectConfig with PROJECTS_JSON env loading"
```

### Task 1.4: In-memory runs table

**Files:**
- Create: `packages/dispatcher/src/a2sdlc_dispatcher/runs_table.py`
- Test: `packages/dispatcher/tests/test_runs_table.py`

- [ ] **Step 1: Write failing test**

```python
# packages/dispatcher/tests/test_runs_table.py
import pytest
from a2sdlc_dispatcher.runs_table import RunsTable, RunNotFound


def test_register_and_lookup():
    t = RunsTable()
    t.register(run_id="r1", ticket_key="A2X-1", repo="acme/webapp", project_key="A2X")
    entry = t.get("r1")
    assert entry.ticket_key == "A2X-1"
    assert entry.repo == "acme/webapp"


def test_lookup_unknown_raises():
    t = RunsTable()
    with pytest.raises(RunNotFound):
        t.get("missing")


def test_finish_removes_entry():
    t = RunsTable()
    t.register(run_id="r1", ticket_key="A2X-1", repo="acme/webapp", project_key="A2X")
    t.finish("r1")
    with pytest.raises(RunNotFound):
        t.get("r1")


def test_active_run_for_ticket():
    t = RunsTable()
    t.register(run_id="r1", ticket_key="A2X-1", repo="acme/webapp", project_key="A2X")
    assert t.active_run_for("A2X-1") == "r1"
    t.finish("r1")
    assert t.active_run_for("A2X-1") is None


def test_in_progress_flag_defaults_false_and_flips_once():
    t = RunsTable()
    t.register(run_id="r1", ticket_key="A2X-1", repo="acme/webapp", project_key="A2X")
    assert t.has_in_progress_been_sent("r1") is False
    t.mark_in_progress_sent("r1")
    assert t.has_in_progress_been_sent("r1") is True
    # Idempotent second call is a no-op.
    t.mark_in_progress_sent("r1")
    assert t.has_in_progress_been_sent("r1") is True
```

- [ ] **Step 2: Run — expect FAIL**

```bash
uv run --package a2sdlc-dispatcher pytest packages/dispatcher/tests/test_runs_table.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `runs_table.py`**

```python
"""In-memory runs table.

Tracks run_id → (ticket_key, repo, project_key). Populated when a Jira
webhook triggers a workflow; consulted when the engine POSTs domain
events so we can resolve back to the correct Jira ticket and project.

Ephemeral: dies on restart. If the dispatcher restarts mid-run, the
in-flight run's domain events will 404 at `/runs/{run_id}/events` — the
engine's subscriber ignores 4xx and the pipeline still finishes with
comments posted elsewhere (console, MLflow). Accepted tradeoff for v1.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import RLock


class RunNotFound(KeyError):
    """Raised when get() is called with an unknown run_id."""


@dataclass(frozen=True)
class RunEntry:
    run_id: str
    ticket_key: str
    repo: str
    project_key: str


class RunsTable:
    def __init__(self) -> None:
        self._by_run: dict[str, RunEntry] = {}
        self._by_ticket: dict[str, str] = {}
        self._in_progress_sent: set[str] = set()
        self._lock = RLock()

    def register(self, *, run_id: str, ticket_key: str, repo: str, project_key: str) -> None:
        with self._lock:
            entry = RunEntry(run_id=run_id, ticket_key=ticket_key, repo=repo, project_key=project_key)
            self._by_run[run_id] = entry
            self._by_ticket[ticket_key] = run_id

    def get(self, run_id: str) -> RunEntry:
        try:
            return self._by_run[run_id]
        except KeyError:
            raise RunNotFound(run_id) from None

    def finish(self, run_id: str) -> None:
        with self._lock:
            entry = self._by_run.pop(run_id, None)
            self._in_progress_sent.discard(run_id)
            if entry and self._by_ticket.get(entry.ticket_key) == run_id:
                self._by_ticket.pop(entry.ticket_key, None)

    def active_run_for(self, ticket_key: str) -> str | None:
        with self._lock:
            return self._by_ticket.get(ticket_key)

    def mark_in_progress_sent(self, run_id: str) -> None:
        """Idempotent — flag that this run has already had its In Progress transition applied."""
        with self._lock:
            self._in_progress_sent.add(run_id)

    def has_in_progress_been_sent(self, run_id: str) -> bool:
        with self._lock:
            return run_id in self._in_progress_sent
```

- [ ] **Step 4: Run — expect PASS**

```bash
uv run --package a2sdlc-dispatcher pytest packages/dispatcher/tests/test_runs_table.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/dispatcher/src/a2sdlc_dispatcher/runs_table.py packages/dispatcher/tests/test_runs_table.py
git commit -m "feat(dispatcher): in-memory runs table"
```

---

## Phase 2: Jira adapter (event translation)

### Task 2.1: Jira client wrapper

**Files:**
- Create: `packages/dispatcher/src/a2sdlc_dispatcher/jira_client.py`
- Test: `packages/dispatcher/tests/test_jira_client.py`

- [ ] **Step 1: Write failing test (with mocks)**

```python
# packages/dispatcher/tests/test_jira_client.py
from unittest.mock import MagicMock
from a2sdlc_dispatcher.jira_client import JiraClient
from a2sdlc_dispatcher.settings import ProjectConfig


def make_project() -> ProjectConfig:
    return ProjectConfig(jira_key="A2X", repo="acme/webapp")


def test_add_comment_calls_jira():
    raw = MagicMock()
    client = JiraClient(raw)
    client.add_comment("A2X-42", "hello")
    raw.issue_add_comment.assert_called_once_with("A2X-42", "hello")


def test_transition_by_name_looks_up_id():
    raw = MagicMock()
    raw.get_issue_transitions.return_value = [
        {"id": "11", "name": "Ready"},
        {"id": "21", "name": "In Progress"},
    ]
    client = JiraClient(raw)
    client.transition("A2X-42", to_status="In Progress")
    raw.issue_transition.assert_called_once_with("A2X-42", "21")


def test_transition_unknown_status_raises():
    raw = MagicMock()
    raw.get_issue_transitions.return_value = [{"id": "11", "name": "Ready"}]
    client = JiraClient(raw)
    import pytest
    with pytest.raises(ValueError, match="no transition named"):
        client.transition("A2X-42", to_status="Done")


def test_find_blocked_by_issues():
    raw = MagicMock()
    raw.jql.return_value = {
        "issues": [
            {"key": "A2X-43"},
            {"key": "A2X-44"},
        ]
    }
    client = JiraClient(raw)
    keys = client.find_issues_blocked_only_by("A2X-42", project_key="A2X", blocked_status="Blocked")
    assert keys == ["A2X-43", "A2X-44"]
    # JQL must ask Jira to return candidates; dispatcher then post-filters for "only blocker done".
    raw.jql.assert_called_once()
```

- [ ] **Step 2: Run — expect FAIL**

```bash
uv run --package a2sdlc-dispatcher pytest packages/dispatcher/tests/test_jira_client.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `jira_client.py`**

```python
"""Thin JiraClient wrapping atlassian-python-api.

Centralizes the Jira calls the dispatcher needs: comment, transition,
and "find candidates blocked only by X" query. Returns native Python
types, not atlassian-api wrappers.
"""
from __future__ import annotations

from typing import Any


class JiraClient:
    def __init__(self, raw: Any) -> None:
        # `raw` is an atlassian.Jira instance.
        self._raw = raw

    def add_comment(self, ticket_key: str, body: str) -> None:
        self._raw.issue_add_comment(ticket_key, body)

    def transition(self, ticket_key: str, *, to_status: str) -> None:
        transitions = self._raw.get_issue_transitions(ticket_key)
        for t in transitions:
            if t.get("name") == to_status:
                self._raw.issue_transition(ticket_key, t["id"])
                return
        raise ValueError(f"no transition named {to_status!r} from current state of {ticket_key}")

    def find_issues_blocked_only_by(
        self, ticket_key: str, *, project_key: str, blocked_status: str
    ) -> list[str]:
        """Return tickets that have ticket_key as a blocker.

        Uses Jira's linkedIssues() JQL — "blocks" is the outward link type
        whose inward label is "is blocked by". A ticket X that `blocks` Y
        appears in `linkedIssues(X, "blocks")` as Y.

        Caller must verify each candidate's OTHER blockers are also Done
        before transitioning it to Ready.
        """
        jql = (
            f'project = "{project_key}" '
            f'AND status = "{blocked_status}" '
            f'AND issue in linkedIssues("{ticket_key}", "blocks")'
        )
        result = self._raw.jql(jql, fields="key")
        return [issue["key"] for issue in result.get("issues", [])]

    def get_blockers(self, ticket_key: str) -> list[tuple[str, str]]:
        """Return [(key, status_name), ...] for each issue this one is blocked by."""
        issue = self._raw.issue(ticket_key, fields="issuelinks,status")
        out: list[tuple[str, str]] = []
        for link in issue["fields"].get("issuelinks", []):
            ltype = link.get("type", {}).get("inward", "")
            if "blocked by" in ltype.lower():
                other = link.get("inwardIssue") or link.get("outwardIssue")
                if other:
                    out.append((other["key"], other["fields"]["status"]["name"]))
        return out
```

- [ ] **Step 4: Run — expect PASS**

```bash
uv run --package a2sdlc-dispatcher pytest packages/dispatcher/tests/test_jira_client.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/dispatcher/src/a2sdlc_dispatcher/jira_client.py packages/dispatcher/tests/test_jira_client.py
git commit -m "feat(dispatcher): JiraClient for comment/transition/blocker queries"
```

### Task 2.2: Event → Jira translator

**Files:**
- Create: `packages/dispatcher/src/a2sdlc_dispatcher/event_translator.py`
- Test: `packages/dispatcher/tests/test_event_translator.py`

- [ ] **Step 1: Write failing test**

```python
# packages/dispatcher/tests/test_event_translator.py
from unittest.mock import MagicMock
from a2sdlc_dispatcher.event_translator import translate_event_to_jira
from a2sdlc_dispatcher.domain_events import RunStarted, StageStarted, StageCompleted, PROpened, PRUpdated, RunCompleted, RunFailed
from a2sdlc_dispatcher.settings import ProjectConfig


def proj() -> ProjectConfig:
    return ProjectConfig(jira_key="A2X", repo="acme/webapp")


def _runs_with_registered(run_id="r1", ticket="A2X-42"):
    from a2sdlc_dispatcher.runs_table import RunsTable
    t = RunsTable()
    t.register(run_id=run_id, ticket_key=ticket, repo="acme/webapp", project_key="A2X")
    return t


def test_first_stage_started_transitions_in_progress_and_dedupes():
    jira = MagicMock()
    runs = _runs_with_registered()
    evt = StageStarted(stage="spec")
    translate_event_to_jira(jira, project=proj(), ticket_key="A2X-42", run_id="r1", runs=runs, event=evt)
    jira.transition.assert_called_once_with("A2X-42", to_status="In Progress")
    # Idempotent: second stage_started in the same run does NOT re-transition.
    jira.reset_mock()
    evt2 = StageStarted(stage="implement")
    translate_event_to_jira(jira, project=proj(), ticket_key="A2X-42", run_id="r1", runs=runs, event=evt2)
    jira.transition.assert_not_called()
    jira.add_comment.assert_called_once()
    assert "implement" in jira.add_comment.call_args[0][1]


def test_stage_completed_ok_non_merge_is_noop():
    jira = MagicMock()
    runs = _runs_with_registered()
    evt = StageCompleted(stage="implement", ok=True)
    translate_event_to_jira(jira, project=proj(), ticket_key="A2X-42", run_id="r1", runs=runs, event=evt)
    jira.transition.assert_not_called()
    jira.add_comment.assert_not_called()


def test_stage_completed_merge_ok_transitions_in_review():
    jira = MagicMock()
    runs = _runs_with_registered()
    evt = StageCompleted(stage="merge", ok=True, summary="PR #1 opened")
    translate_event_to_jira(jira, project=proj(), ticket_key="A2X-42", run_id="r1", runs=runs, event=evt)
    jira.transition.assert_called_once_with("A2X-42", to_status="In Review")


def test_stage_completed_failure_transitions_to_blocked():
    jira = MagicMock()
    runs = _runs_with_registered()
    evt = StageCompleted(stage="implement", ok=False, summary="syntax error")
    translate_event_to_jira(jira, project=proj(), ticket_key="A2X-42", run_id="r1", runs=runs, event=evt)
    jira.transition.assert_called_once_with("A2X-42", to_status="Blocked")
    jira.add_comment.assert_called_once()
    assert "syntax error" in jira.add_comment.call_args[0][1]


def test_pr_opened_comments_pr_url():
    jira = MagicMock()
    runs = _runs_with_registered()
    evt = PROpened(url="https://github.com/x/y/pull/1", base="main", head="x/y")
    translate_event_to_jira(jira, project=proj(), ticket_key="A2X-42", run_id="r1", runs=runs, event=evt)
    jira.add_comment.assert_called_once()
    assert "pull/1" in jira.add_comment.call_args[0][1]


def test_pr_updated_approved_transitions_in_review():
    jira = MagicMock()
    runs = _runs_with_registered()
    evt = PRUpdated(url="https://github.com/x/y/pull/1", update_kind="approved")
    translate_event_to_jira(jira, project=proj(), ticket_key="A2X-42", run_id="r1", runs=runs, event=evt)
    jira.transition.assert_called_once_with("A2X-42", to_status="In Review")


def test_run_failed_transitions_blocked():
    jira = MagicMock()
    runs = _runs_with_registered()
    evt = RunFailed(error="rate limit")
    translate_event_to_jira(jira, project=proj(), ticket_key="A2X-42", run_id="r1", runs=runs, event=evt)
    jira.transition.assert_called_once_with("A2X-42", to_status="Blocked")
    jira.add_comment.assert_called_once()
    assert "rate limit" in jira.add_comment.call_args[0][1]


def test_unknown_event_is_silent():
    from a2sdlc_dispatcher.domain_events import UnknownEvent
    jira = MagicMock()
    runs = _runs_with_registered()
    evt = UnknownEvent(kind="future_v2")
    translate_event_to_jira(jira, project=proj(), ticket_key="A2X-42", run_id="r1", runs=runs, event=evt)
    jira.transition.assert_not_called()
    jira.add_comment.assert_not_called()
```

- [ ] **Step 2: Run — expect FAIL**

```bash
uv run --package a2sdlc-dispatcher pytest packages/dispatcher/tests/test_event_translator.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `event_translator.py`**

```python
"""Translate engine-emitted domain events into Jira comments + transitions.

Key semantics:

- Engine invocations in CI are one-stage-per-run-per-process. To avoid spamming
  Jira with re-transitions, the dispatcher itself dedupes "Ready → In Progress"
  using a flag in RunsTable — fired on the FIRST stage_started received for
  a given run_id. Subsequent stage_started events become comments only.
- The final `stage_completed(stage="merge", ok=True)` means the PR has been
  opened and is awaiting human merge — transition to In Review.
- Any `stage_completed(ok=False)` transitions to Blocked with the summary.
"""
from __future__ import annotations

from a2sdlc_dispatcher.domain_events import (
    PROpened,
    PRUpdated,
    RunCompleted,
    RunFailed,
    StageCompleted,
    StageStarted,
    UnknownEvent,
)
from a2sdlc_dispatcher.jira_client import JiraClient
from a2sdlc_dispatcher.runs_table import RunsTable
from a2sdlc_dispatcher.settings import ProjectConfig


def translate_event_to_jira(
    jira: JiraClient,
    *,
    project: ProjectConfig,
    ticket_key: str,
    run_id: str,
    runs: RunsTable,
    event,
) -> None:
    """Dispatch on event type.

    Unknown event kinds are silently ignored (forward compat).
    """
    if isinstance(event, StageStarted):
        if not runs.has_in_progress_been_sent(run_id):
            jira.transition(ticket_key, to_status=project.status_in_progress)
            runs.mark_in_progress_sent(run_id)
            jira.add_comment(ticket_key, f":rocket: Run started — entering stage: **{event.stage}**")
        else:
            jira.add_comment(ticket_key, f"▶ Entering stage: **{event.stage}**")

    elif isinstance(event, StageCompleted):
        if not event.ok:
            jira.transition(ticket_key, to_status=project.status_blocked)
            summary = event.summary or "(no summary)"
            jira.add_comment(ticket_key, f":x: Stage `{event.stage}` failed: {summary}")
            return
        if event.stage == "merge":
            jira.transition(ticket_key, to_status=project.status_review)
            body = ":white_check_mark: Merge stage complete — PR awaiting human review/merge"
            if event.summary:
                body += f"\n{event.summary}"
            jira.add_comment(ticket_key, body)

    elif isinstance(event, PROpened):
        jira.add_comment(ticket_key, f":open_file_folder: PR opened: {event.url} ({event.head} → {event.base})")

    elif isinstance(event, PRUpdated):
        jira.add_comment(ticket_key, f":arrows_counterclockwise: PR {event.update_kind}: {event.url}")
        if event.update_kind == "approved":
            jira.transition(ticket_key, to_status=project.status_review)

    elif isinstance(event, RunCompleted):
        # Kept for forward-compat; current engine drives review transition via
        # StageCompleted(stage="merge", ok=True) instead.
        if event.outcome == "awaiting_merge":
            jira.transition(ticket_key, to_status=project.status_review)

    elif isinstance(event, RunFailed):
        jira.transition(ticket_key, to_status=project.status_blocked)
        body = f":x: Run failed: {event.error}"
        if event.mlflow_url:
            body += f"\nMLflow: {event.mlflow_url}"
        jira.add_comment(ticket_key, body)

    elif isinstance(event, UnknownEvent):
        # Forward-compat: engine may emit kinds the dispatcher doesn't understand yet.
        return
```

- [ ] **Step 4: Run — expect PASS**

```bash
uv run --package a2sdlc-dispatcher pytest packages/dispatcher/tests/test_event_translator.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/dispatcher/src/a2sdlc_dispatcher/event_translator.py packages/dispatcher/tests/test_event_translator.py
git commit -m "feat(dispatcher): event → Jira translator with per-project status names"
```

---

## Phase 3: Webhook routes

### Task 3.1: Webhook signature verification helpers

**Files:**
- Create: `packages/dispatcher/src/a2sdlc_dispatcher/webhook_sig.py`
- Test: `packages/dispatcher/tests/test_webhook_sig.py`

- [ ] **Step 1: Write failing test**

```python
# packages/dispatcher/tests/test_webhook_sig.py
import hashlib
import hmac
import pytest
from a2sdlc_dispatcher.webhook_sig import verify_github_sig, verify_jira_sig, SigError

SECRET = b"shared-secret"


def gh_sig(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET, body, hashlib.sha256).hexdigest()


def test_github_valid():
    body = b'{"x":1}'
    verify_github_sig(body=body, header=gh_sig(body), secret=SECRET)  # should not raise


def test_github_invalid():
    body = b'{"x":1}'
    with pytest.raises(SigError):
        verify_github_sig(body=body, header="sha256=deadbeef", secret=SECRET)


def test_github_missing_header():
    with pytest.raises(SigError, match="missing"):
        verify_github_sig(body=b"{}", header=None, secret=SECRET)


def test_jira_valid():
    body = b'{"y":2}'
    sig = hmac.new(SECRET, body, hashlib.sha256).hexdigest()
    verify_jira_sig(body=body, header=sig, secret=SECRET)


def test_jira_invalid():
    with pytest.raises(SigError):
        verify_jira_sig(body=b'{"y":2}', header="bogus", secret=SECRET)
```

- [ ] **Step 2: Run — expect FAIL**

```bash
uv run --package a2sdlc-dispatcher pytest packages/dispatcher/tests/test_webhook_sig.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `webhook_sig.py`**

```python
"""Webhook signature verification.

Jira Cloud sends a raw hex HMAC-SHA256 in X-Hub-Signature (when configured
with a shared secret). GitHub sends `sha256=<hex>` in X-Hub-Signature-256.
"""
from __future__ import annotations

import hashlib
import hmac


class SigError(Exception):
    pass


def verify_github_sig(*, body: bytes, header: str | None, secret: bytes) -> None:
    if not header:
        raise SigError("missing X-Hub-Signature-256 header")
    if not header.startswith("sha256="):
        raise SigError("malformed signature header")
    expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
    given = header[len("sha256=") :]
    if not hmac.compare_digest(expected, given):
        raise SigError("signature mismatch")


def verify_jira_sig(*, body: bytes, header: str | None, secret: bytes) -> None:
    if not header:
        raise SigError("missing X-Hub-Signature header")
    expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, header):
        raise SigError("signature mismatch")
```

- [ ] **Step 4: Run — expect PASS**

```bash
uv run --package a2sdlc-dispatcher pytest packages/dispatcher/tests/test_webhook_sig.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/dispatcher/src/a2sdlc_dispatcher/webhook_sig.py packages/dispatcher/tests/test_webhook_sig.py
git commit -m "feat(dispatcher): webhook signature verification helpers"
```

### Task 3.2: GH App client — workflow_dispatch trigger

**Files:**
- Create: `packages/dispatcher/src/a2sdlc_dispatcher/gh_app.py`
- Test: `packages/dispatcher/tests/test_gh_app.py`

- [ ] **Step 1: Write failing test**

```python
# packages/dispatcher/tests/test_gh_app.py
from unittest.mock import AsyncMock, MagicMock
import pytest
from a2sdlc_dispatcher.gh_app import GHAppClient


@pytest.mark.asyncio
async def test_trigger_workflow_dispatch_calls_right_endpoint():
    http = AsyncMock()
    http.post.return_value = MagicMock(status_code=204)

    client = GHAppClient(
        http=http,
        app_id=1,
        private_key_pem="dummy",
        installation_id=1,
        installation_token="ghs_xxx",
    )
    await client.trigger_workflow_dispatch(
        repo="acme/webapp",
        workflow_filename="a2sdlc-split.yml",
        ref="main",
        inputs={"ticket_key": "A2X-42", "run_id": "r1"},
    )

    http.post.assert_awaited_once()
    url = http.post.await_args.args[0]
    assert url == "https://api.github.com/repos/acme/webapp/actions/workflows/a2sdlc-split.yml/dispatches"
    body = http.post.await_args.kwargs["json"]
    assert body["ref"] == "main"
    assert body["inputs"]["ticket_key"] == "A2X-42"
    assert http.post.await_args.kwargs["headers"]["Authorization"] == "Bearer ghs_xxx"
```

- [ ] **Step 2: Run — expect FAIL**

```bash
uv run --package a2sdlc-dispatcher pytest packages/dispatcher/tests/test_gh_app.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `gh_app.py` with lazy-refreshing installation tokens**

GitHub installation tokens expire after 1h. To avoid a "works for the first hour, silently breaks forever" failure mode, the client mints a fresh installation token via JWT exchange on demand and caches it until 5 minutes before expiry.

```python
"""GitHub App helper — mints App JWT + exchanges for installation tokens.

Installation tokens are short-lived (1h). We cache the current token in
memory and refresh on demand when we're within 5 minutes of expiry.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt


def mint_app_jwt(*, app_id: int, private_key_pem: str, ttl_seconds: int = 540) -> str:
    """Mint a short-lived JWT for the GH App itself (max 10 min per GH policy)."""
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + ttl_seconds, "iss": app_id}
    return jwt.encode(payload, private_key_pem, algorithm="RS256")


async def exchange_for_installation_token(
    *, http: httpx.AsyncClient, app_jwt: str, installation_id: int
) -> tuple[str, int]:
    """Exchange an App JWT for a short-lived installation token.

    Returns (token, expires_at_unix_seconds).
    """
    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {app_jwt}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    r = await http.post(url, headers=headers)
    r.raise_for_status()
    data = r.json()
    # GH returns expires_at as ISO8601; parse into unix seconds.
    from datetime import datetime, timezone as tz

    expires_at = int(datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00")).timestamp())
    return data["token"], expires_at


@dataclass
class _TokenCache:
    token: str = ""
    expires_at: int = 0


class GHAppClient:
    """Triggers workflow dispatches with an installation token that auto-refreshes."""

    _REFRESH_MARGIN = 300  # refresh if within 5 minutes of expiry

    def __init__(
        self,
        *,
        http: httpx.AsyncClient,
        app_id: int,
        private_key_pem: str,
        installation_id: int,
        # Test-only: inject a fixed token to bypass the JWT exchange.
        installation_token: str | None = None,
    ) -> None:
        self._http = http
        self._app_id = app_id
        self._pem = private_key_pem
        self._installation_id = installation_id
        self._cache = _TokenCache()
        if installation_token is not None:
            # Test path: far-future expiry so we never try to refresh.
            self._cache = _TokenCache(token=installation_token, expires_at=2**31 - 1)

    async def _current_token(self) -> str:
        now = int(time.time())
        if self._cache.token and now < self._cache.expires_at - self._REFRESH_MARGIN:
            return self._cache.token
        app_jwt = mint_app_jwt(app_id=self._app_id, private_key_pem=self._pem)
        token, expires_at = await exchange_for_installation_token(
            http=self._http, app_jwt=app_jwt, installation_id=self._installation_id
        )
        self._cache = _TokenCache(token=token, expires_at=expires_at)
        return token

    async def trigger_workflow_dispatch(
        self,
        *,
        repo: str,
        workflow_filename: str,
        ref: str,
        inputs: dict[str, Any],
    ) -> None:
        token = await self._current_token()
        url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow_filename}/dispatches"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        r = await self._http.post(url, json={"ref": ref, "inputs": inputs}, headers=headers)
        r.raise_for_status()
```

- [ ] **Step 3a: Update the test to use the test-path constructor**

The existing test injects `installation_token="ghs_xxx"` directly. That still works because the test-only kwarg fast-paths the cache. Ensure the test constructs `GHAppClient` as:

```python
client = GHAppClient(
    http=http,
    app_id=1,
    private_key_pem="dummy",
    installation_id=1,
    installation_token="ghs_xxx",
)
```

- [ ] **Step 4: Add `pytest-asyncio` to the workspace dev deps (if not already)**

Check root `pyproject.toml` — `pytest-asyncio` should already be present (from the engine). Add config marker:

```toml
[tool.pytest.ini_options]
# (existing)
asyncio_mode = "auto"
```

- [ ] **Step 5: Run — expect PASS**

```bash
uv run --package a2sdlc-dispatcher pytest packages/dispatcher/tests/test_gh_app.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/dispatcher/src/a2sdlc_dispatcher/gh_app.py packages/dispatcher/tests/test_gh_app.py pyproject.toml
git commit -m "feat(dispatcher): GHAppClient for workflow_dispatch trigger"
```

### Task 3.3: POST /jira/events route

**Files:**
- Create: `packages/dispatcher/src/a2sdlc_dispatcher/routes_jira.py`
- Modify: `packages/dispatcher/src/a2sdlc_dispatcher/server.py`
- Test: `packages/dispatcher/tests/test_routes_jira.py`

- [ ] **Step 1: Write failing test**

```python
# packages/dispatcher/tests/test_routes_jira.py
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock
import pytest
from fastapi.testclient import TestClient

from a2sdlc_dispatcher.routes_jira import build_router
from a2sdlc_dispatcher.settings import ProjectConfig
from a2sdlc_dispatcher.runs_table import RunsTable


def _build_app(settings_mock, gh_app_mock, runs):
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(build_router(settings=settings_mock, gh_app=gh_app_mock, runs=runs))
    return app


def _event_payload(ticket_key: str, to_status: str, description: str = "As a user, I want X.") -> bytes:
    return json.dumps({
        "webhookEvent": "jira:issue_updated",
        "issue": {
            "key": ticket_key,
            "fields": {"status": {"name": to_status}, "description": description},
        },
        "changelog": {"items": [{"field": "status", "toString": to_status}]},
    }).encode()


def _sign(body: bytes, secret: bytes) -> str:
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


def _settings():
    s = MagicMock()
    s.jira_webhook_secret.get_secret_value.return_value = "shh"
    s.hmac_signing_key.get_secret_value.return_value = "k" * 32
    s.project_by_key.return_value = ProjectConfig(jira_key="A2X", repo="acme/webapp")
    s.self_url = "https://dispatcher.yose.tld"
    return s


@pytest.mark.asyncio
async def test_ready_transition_triggers_workflow():
    settings = _settings()
    gh = AsyncMock()
    runs = RunsTable()
    app = _build_app(settings, gh, runs)
    client = TestClient(app)

    body = _event_payload("A2X-42", "Ready")
    r = client.post(
        "/jira/events",
        content=body,
        headers={"X-Hub-Signature": _sign(body, b"shh")},
    )
    assert r.status_code == 202
    gh.trigger_workflow_dispatch.assert_awaited_once()
    call = gh.trigger_workflow_dispatch.await_args.kwargs
    assert call["repo"] == "acme/webapp"
    assert call["inputs"]["ticket_key"] == "A2X-42"
    assert call["inputs"]["ticket_body"] == "As a user, I want X."
    assert call["inputs"]["dispatcher_url"] == "https://dispatcher.yose.tld"
    assert "run_id" in call["inputs"]
    assert "run_hmac" in call["inputs"]
    # dispatcher registered the run
    assert runs.active_run_for("A2X-42") is not None


def test_bad_signature_rejected():
    settings = _settings()
    gh = AsyncMock()
    runs = RunsTable()
    app = _build_app(settings, gh, runs)
    client = TestClient(app)
    body = _event_payload("A2X-42", "Ready")
    r = client.post(
        "/jira/events",
        content=body,
        headers={"X-Hub-Signature": "bogus"},
    )
    assert r.status_code == 401


def test_non_ready_status_ignored():
    settings = _settings()
    gh = AsyncMock()
    runs = RunsTable()
    app = _build_app(settings, gh, runs)
    client = TestClient(app)
    body = _event_payload("A2X-42", "In Progress")
    r = client.post(
        "/jira/events",
        content=body,
        headers={"X-Hub-Signature": _sign(body, b"shh")},
    )
    assert r.status_code == 204
    gh.trigger_workflow_dispatch.assert_not_awaited()
```

- [ ] **Step 2: Run — expect FAIL**

```bash
uv run --package a2sdlc-dispatcher pytest packages/dispatcher/tests/test_routes_jira.py -v
```

Expected: FAIL (module missing).

- [ ] **Step 3: Implement `routes_jira.py`**

```python
"""POST /jira/events — Jira webhook ingestion."""
from __future__ import annotations

from typing import Any

import ulid
from fastapi import APIRouter, HTTPException, Request

from a2sdlc_dispatcher.hmac_token import mint_token
from a2sdlc_dispatcher.gh_app import GHAppClient
from a2sdlc_dispatcher.runs_table import RunsTable
from a2sdlc_dispatcher.settings import Settings
from a2sdlc_dispatcher.webhook_sig import SigError, verify_jira_sig


def build_router(*, settings: Settings, gh_app: GHAppClient, runs: RunsTable) -> APIRouter:
    router = APIRouter()

    @router.post("/jira/events")
    async def jira_events(request: Request):
        body = await request.body()
        secret = settings.jira_webhook_secret.get_secret_value().encode() if settings.jira_webhook_secret else None
        if secret is not None:
            try:
                verify_jira_sig(body=body, header=request.headers.get("X-Hub-Signature"), secret=secret)
            except SigError:
                raise HTTPException(status_code=401, detail="bad signature")

        payload: dict[str, Any] = await request.json()
        issue = payload.get("issue") or {}
        ticket_key = issue.get("key")
        fields = issue.get("fields", {}) or {}
        status_name = fields.get("status", {}).get("name")
        # Jira webhook payload carries the issue description in fields.description
        # (may be an ADF object or a plain string depending on Jira config).
        ticket_body_raw = fields.get("description") or ""
        if isinstance(ticket_body_raw, dict):
            # Minimal ADF → text fallback: concatenate content.*.text. Good enough for v1;
            # full ADF rendering can land post-demo.
            ticket_body = _flatten_adf(ticket_body_raw)
        else:
            ticket_body = str(ticket_body_raw)
        # Workflow inputs have a soft ~65535 char cap; truncate conservatively.
        if len(ticket_body) > 60_000:
            ticket_body = ticket_body[:60_000] + "\n\n…(truncated)"

        if not ticket_key or not status_name:
            raise HTTPException(status_code=400, detail="missing issue.key or status.name")

        project_key = ticket_key.split("-")[0]
        try:
            project = settings.project_by_key(project_key)
        except KeyError:
            # Not a project we own; silently ignore.
            return _no_content()

        if status_name != project.status_ready:
            return _no_content()

        # Build run identity + capability token.
        run_id = str(ulid.ULID())
        key_bytes = settings.hmac_signing_key.get_secret_value().encode()
        run_hmac = mint_token(run_id, ticket_key, key=key_bytes, ttl_seconds=86400)

        runs.register(run_id=run_id, ticket_key=ticket_key, repo=project.repo, project_key=project_key)

        dispatcher_url = settings.self_url or str(request.base_url).rstrip("/")

        await gh_app.trigger_workflow_dispatch(
            repo=project.repo,
            workflow_filename="a2sdlc-split.yml",
            ref=project.default_base,
            inputs={
                "ticket_key": ticket_key,
                "ticket_body": ticket_body,
                "run_id": run_id,
                "run_hmac": run_hmac,
                "base_branch": project.default_base,
                "dispatcher_url": dispatcher_url,
            },
        )

        from fastapi.responses import Response
        return Response(status_code=202)


def _flatten_adf(node: dict) -> str:
    """Recursively collect ADF text nodes into a single string."""
    out: list[str] = []
    if isinstance(node, dict):
        if node.get("type") == "text" and "text" in node:
            out.append(str(node["text"]))
        for child in node.get("content", []) or []:
            out.append(_flatten_adf(child))
        if node.get("type") in {"paragraph", "heading", "bulletList", "orderedList", "listItem"}:
            out.append("\n")
    return "".join(out)

    return router


def _no_content():
    from fastapi.responses import Response
    return Response(status_code=204)
```

- [ ] **Step 4: Wire router into `server.py`**

Modify `server.py`:

```python
"""FastAPI app entry point."""
from __future__ import annotations

import httpx
from fastapi import FastAPI

from a2sdlc_dispatcher.gh_app import GHAppClient
from a2sdlc_dispatcher.routes_jira import build_router as build_jira_router
from a2sdlc_dispatcher.runs_table import RunsTable
from a2sdlc_dispatcher.settings import Settings


def create_app() -> FastAPI:
    app = FastAPI(title="a2sdlc-dispatcher", version="0.1.0")
    settings = Settings()
    http = httpx.AsyncClient(timeout=30.0)
    # GH App auth: JWT → installation token exchange, lazy refresh on each
    # trigger call when the cached token is within 5 min of expiry.
    gh_app = GHAppClient(
        http=http,
        app_id=settings.gh_app_id,
        private_key_pem=settings.gh_app_private_key.get_secret_value(),
        installation_id=settings.gh_app_installation_id,
    )
    runs = RunsTable()

    app.include_router(build_jira_router(settings=settings, gh_app=gh_app, runs=runs))

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    return app


app = create_app()


def run() -> None:
    import uvicorn
    uvicorn.run("a2sdlc_dispatcher.server:app", host="0.0.0.0", port=8000, log_level="info")
```

- [ ] **Step 5: Run — expect PASS**

```bash
uv run --package a2sdlc-dispatcher pytest packages/dispatcher/tests/test_routes_jira.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/dispatcher/src/a2sdlc_dispatcher/routes_jira.py packages/dispatcher/src/a2sdlc_dispatcher/server.py packages/dispatcher/tests/test_routes_jira.py
git commit -m "feat(dispatcher): POST /jira/events triggers workflow_dispatch"
```

### Task 3.4: POST /runs/{run_id}/events route

**Files:**
- Create: `packages/dispatcher/src/a2sdlc_dispatcher/routes_events.py`
- Modify: `packages/dispatcher/src/a2sdlc_dispatcher/server.py`
- Test: `packages/dispatcher/tests/test_routes_events.py`

- [ ] **Step 1: Write failing test**

```python
# packages/dispatcher/tests/test_routes_events.py
import json
from unittest.mock import MagicMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from a2sdlc_dispatcher.hmac_token import mint_token
from a2sdlc_dispatcher.routes_events import build_router
from a2sdlc_dispatcher.runs_table import RunsTable
from a2sdlc_dispatcher.settings import ProjectConfig

KEY = b"k" * 32


def _app(jira, settings_mock, runs):
    app = FastAPI()
    app.include_router(build_router(settings=settings_mock, jira=jira, runs=runs))
    return app


def _settings():
    s = MagicMock()
    s.hmac_signing_key.get_secret_value.return_value = "k" * 32
    s.project_by_key.return_value = ProjectConfig(jira_key="A2X", repo="acme/webapp")
    return s


def test_stage_started_routed_to_jira():
    jira = MagicMock()
    settings = _settings()
    runs = RunsTable()
    runs.register(run_id="r1", ticket_key="A2X-42", repo="acme/webapp", project_key="A2X")
    client = TestClient(_app(jira, settings, runs))
    token = mint_token("r1", "A2X-42", key=KEY, ttl_seconds=60)
    r = client.post(
        "/runs/r1/events",
        json={"kind": "stage_started", "stage": "implement"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 202
    jira.add_comment.assert_called_once()


def test_bad_token_rejected():
    jira = MagicMock()
    settings = _settings()
    runs = RunsTable()
    runs.register(run_id="r1", ticket_key="A2X-42", repo="acme/webapp", project_key="A2X")
    client = TestClient(_app(jira, settings, runs))
    r = client.post(
        "/runs/r1/events",
        json={"kind": "stage_started", "stage": "implement"},
        headers={"Authorization": "Bearer nope"},
    )
    assert r.status_code == 401


def test_unknown_run_404():
    jira = MagicMock()
    settings = _settings()
    runs = RunsTable()
    client = TestClient(_app(jira, settings, runs))
    token = mint_token("rX", "A2X-42", key=KEY, ttl_seconds=60)
    r = client.post(
        "/runs/rX/events",
        json={"kind": "stage_started", "stage": "x"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404
```

- [ ] **Step 2: Run — expect FAIL**

```bash
uv run --package a2sdlc-dispatcher pytest packages/dispatcher/tests/test_routes_events.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `routes_events.py`**

```python
"""POST /runs/{run_id}/events — ingest domain events from running engine."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Header, Request

from a2sdlc_dispatcher.domain_events import DomainEventAdapter
from a2sdlc_dispatcher.event_translator import translate_event_to_jira
from a2sdlc_dispatcher.hmac_token import TokenError, verify_token
from a2sdlc_dispatcher.jira_client import JiraClient
from a2sdlc_dispatcher.runs_table import RunNotFound, RunsTable
from a2sdlc_dispatcher.settings import Settings


def build_router(*, settings: Settings, jira: JiraClient, runs: RunsTable) -> APIRouter:
    router = APIRouter()

    @router.post("/runs/{run_id}/events", status_code=202)
    async def ingest(run_id: str, request: Request, authorization: str | None = Header(None)):
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        token = authorization.removeprefix("Bearer ").strip()

        key = settings.hmac_signing_key.get_secret_value().encode()
        try:
            claims = verify_token(token, key=key)
        except TokenError as e:
            raise HTTPException(status_code=401, detail=str(e)) from None

        if claims.run_id != run_id:
            raise HTTPException(status_code=401, detail="token/run mismatch")

        try:
            entry = runs.get(run_id)
        except RunNotFound:
            raise HTTPException(status_code=404, detail="run not found") from None

        payload = await request.json()
        event = DomainEventAdapter.validate_python(payload)
        project = settings.project_by_key(entry.project_key)
        translate_event_to_jira(jira, project=project, ticket_key=entry.ticket_key, event=event)
        return {"ok": True}

    return router
```

- [ ] **Step 4: Wire into `server.py`**

Add to `create_app()`:

```python
from atlassian import Jira as AtlassianJira
from a2sdlc_dispatcher.jira_client import JiraClient
from a2sdlc_dispatcher.routes_events import build_router as build_events_router

raw_jira = AtlassianJira(
    url=settings.jira_base_url,
    username=settings.jira_user,
    password=settings.jira_token.get_secret_value(),
)
jira = JiraClient(raw_jira)

app.include_router(build_events_router(settings=settings, jira=jira, runs=runs))
```

- [ ] **Step 5: Run — expect PASS**

```bash
uv run --package a2sdlc-dispatcher pytest packages/dispatcher/tests/test_routes_events.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/dispatcher/src/a2sdlc_dispatcher/routes_events.py packages/dispatcher/src/a2sdlc_dispatcher/server.py packages/dispatcher/tests/test_routes_events.py
git commit -m "feat(dispatcher): POST /runs/{run_id}/events ingests engine domain events"
```

### Task 3.5: POST /gh/events route (PR merged → unblock dependents)

**Files:**
- Create: `packages/dispatcher/src/a2sdlc_dispatcher/routes_github.py`
- Modify: `packages/dispatcher/src/a2sdlc_dispatcher/server.py`
- Test: `packages/dispatcher/tests/test_routes_github.py`

- [ ] **Step 1: Write failing test**

```python
# packages/dispatcher/tests/test_routes_github.py
import hashlib
import hmac
import json
import re
from unittest.mock import MagicMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from a2sdlc_dispatcher.routes_github import build_router
from a2sdlc_dispatcher.settings import ProjectConfig


SECRET = b"shh"


def _settings():
    s = MagicMock()
    s.gh_webhook_secret.get_secret_value.return_value = "shh"
    s.project_by_key.return_value = ProjectConfig(jira_key="A2X", repo="acme/webapp")
    return s


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET, body, hashlib.sha256).hexdigest()


def _pr_merged_body(pr_body: str, repo: str = "acme/webapp") -> bytes:
    return json.dumps({
        "action": "closed",
        "pull_request": {"merged": True, "body": pr_body, "html_url": f"https://github.com/{repo}/pull/1"},
        "repository": {"full_name": repo},
    }).encode()


def _app(jira, settings):
    app = FastAPI()
    app.include_router(build_router(settings=settings, jira=jira))
    return app


def test_pr_merged_transitions_and_unblocks_dependents():
    jira = MagicMock()
    jira.find_issues_blocked_only_by.return_value = ["A2X-43"]
    jira.get_blockers.return_value = [("A2X-42", "Done")]

    settings = _settings()
    client = TestClient(_app(jira, settings))
    body = _pr_merged_body("Closes A2X-42")
    r = client.post(
        "/gh/events",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": _sign(body),
        },
    )
    assert r.status_code == 202
    # closed ticket → Done
    jira.transition.assert_any_call("A2X-42", to_status="Done")
    # dependent's other blockers (none) → dependent transitioned to Ready
    jira.transition.assert_any_call("A2X-43", to_status="Ready")


def test_dependent_with_remaining_blockers_not_transitioned():
    jira = MagicMock()
    jira.find_issues_blocked_only_by.return_value = ["A2X-43"]
    # Dependent has ANOTHER blocker that's not done yet.
    jira.get_blockers.return_value = [("A2X-42", "Done"), ("A2X-50", "In Progress")]

    settings = _settings()
    client = TestClient(_app(jira, settings))
    body = _pr_merged_body("Closes A2X-42")
    r = client.post(
        "/gh/events",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": _sign(body),
        },
    )
    assert r.status_code == 202
    jira.transition.assert_any_call("A2X-42", to_status="Done")
    # A2X-43 must NOT be transitioned to Ready
    ready_calls = [c for c in jira.transition.call_args_list if "Ready" in str(c)]
    assert ready_calls == []


def test_pr_without_closes_is_ignored():
    jira = MagicMock()
    settings = _settings()
    client = TestClient(_app(jira, settings))
    body = _pr_merged_body("Some PR body with no closes directive")
    r = client.post(
        "/gh/events",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": _sign(body),
        },
    )
    assert r.status_code == 204
    jira.transition.assert_not_called()
```

- [ ] **Step 2: Run — expect FAIL**

```bash
uv run --package a2sdlc-dispatcher pytest packages/dispatcher/tests/test_routes_github.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `routes_github.py`**

```python
"""POST /gh/events — GitHub webhook ingestion (PR merged)."""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request

from a2sdlc_dispatcher.jira_client import JiraClient
from a2sdlc_dispatcher.settings import Settings
from a2sdlc_dispatcher.webhook_sig import SigError, verify_github_sig

CLOSES_PATTERN = re.compile(r"[Cc]loses?\s+([A-Z]+-\d+)")


def _no_content():
    from fastapi.responses import Response
    return Response(status_code=204)


def build_router(*, settings: Settings, jira: JiraClient) -> APIRouter:
    router = APIRouter()

    @router.post("/gh/events")
    async def gh_events(request: Request):
        body = await request.body()
        secret = settings.gh_webhook_secret.get_secret_value().encode() if settings.gh_webhook_secret else None
        if secret is not None:
            try:
                verify_github_sig(body=body, header=request.headers.get("X-Hub-Signature-256"), secret=secret)
            except SigError:
                raise HTTPException(status_code=401, detail="bad signature")

        event = request.headers.get("X-GitHub-Event")
        if event != "pull_request":
            return _no_content()

        payload = await request.json()
        if payload.get("action") != "closed":
            return _no_content()
        pr = payload.get("pull_request", {})
        if not pr.get("merged"):
            return _no_content()

        pr_body = pr.get("body") or ""
        match = CLOSES_PATTERN.search(pr_body)
        if not match:
            return _no_content()

        ticket_key = match.group(1)
        project_key = ticket_key.split("-")[0]
        project = settings.project_by_key(project_key)

        # Transition the merged ticket to Done.
        jira.transition(ticket_key, to_status=project.status_done)

        # Find dependents and transition those with no remaining blockers.
        candidates = jira.find_issues_blocked_only_by(
            ticket_key, project_key=project_key, blocked_status=project.status_blocked
        )
        for dep in candidates:
            blockers = jira.get_blockers(dep)
            all_done = all(status == project.status_done for _key, status in blockers)
            if all_done:
                jira.transition(dep, to_status=project.status_ready)

        from fastapi.responses import Response
        return Response(status_code=202)

    return router
```

- [ ] **Step 4: Wire into `server.py`**

Add to `create_app()`:

```python
from a2sdlc_dispatcher.routes_github import build_router as build_gh_router

app.include_router(build_gh_router(settings=settings, jira=jira))
```

- [ ] **Step 5: Run — expect PASS**

```bash
uv run --package a2sdlc-dispatcher pytest packages/dispatcher/tests/test_routes_github.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/dispatcher/src/a2sdlc_dispatcher/routes_github.py packages/dispatcher/src/a2sdlc_dispatcher/server.py packages/dispatcher/tests/test_routes_github.py
git commit -m "feat(dispatcher): POST /gh/events transitions merged tickets + unblocks"
```

---

## Phase 4: Engine additions (WorkflowInputReader + DispatcherEventSubscriber)

### Task 4.1: `WorkflowInputReader` — `WorkAdapter` impl for Mode 1

**Files:**
- Create: `packages/engine/src/a2sdlc/adapters/work/workflow_input.py`
- Test: `packages/engine/tests/adapters/work/test_workflow_input.py`

- [ ] **Step 1: Read existing `WorkAdapter` protocol**

```bash
sed -n '1,80p' packages/engine/src/a2sdlc/adapters/work/__init__.py
```

Note the protocol methods. The `WorkflowInputReader` must implement the same contract (at least the ones actually invoked during a stage; others can `raise NotImplementedError`).

- [ ] **Step 2: Write failing test**

```python
# packages/engine/tests/adapters/work/test_workflow_input.py
import json
import os
from pathlib import Path

import pytest

from a2sdlc.adapters.work.workflow_input import WorkflowInputReader
from a2sdlc.domain.pipeline_event import PipelineEvent
from a2sdlc.domain.models import StageName


def test_parse_event_returns_pipeline_event(tmp_path, monkeypatch):
    monkeypatch.setenv("TICKET_KEY", "A2X-42")
    monkeypatch.setenv("A2SDLC_TRIGGER_STAGE", "spec")
    monkeypatch.setenv("TICKET_BODY", "As a user, I want auth.")
    reader = WorkflowInputReader()
    evt = reader.parse_event()
    assert evt.key == "A2X-42"
    assert evt.trigger_stage == StageName.SPEC


def test_get_ticket_body_returns_env(monkeypatch):
    monkeypatch.setenv("TICKET_KEY", "A2X-42")
    monkeypatch.setenv("TICKET_BODY", "hello world")
    monkeypatch.setenv("A2SDLC_TRIGGER_STAGE", "spec")
    reader = WorkflowInputReader()
    assert reader.get_ticket_body("A2X-42") == "hello world"
```

- [ ] **Step 3: Run — expect FAIL**

```bash
uv run --package a2sdlc-engine pytest packages/engine/tests/adapters/work/test_workflow_input.py -v
```

Expected: FAIL.

- [ ] **Step 4: Implement `workflow_input.py`**

```python
"""WorkflowInputReader — WorkAdapter impl for Mode 1 (dispatcher-driven).

Reads ticket context from env vars that the dispatcher set via workflow_dispatch
inputs. Does not call Jira. Engine remains ticket-system-agnostic.

Writes (comments, transitions) are NOT performed here — those go over HTTP
via DispatcherEventSubscriber. The write methods below are NO-OPS returning
sentinel values, not NotImplementedError, because CommentManager invokes them
in the engine's normal path and we must not crash Mode 1 runs.
"""
from __future__ import annotations

import os

from a2sdlc.domain.exceptions import SkipEvent
from a2sdlc.domain.models import StageName
from a2sdlc.domain.pipeline_event import PipelineEvent

_SENTINEL_COMMENT_ID = "dispatcher-routed"


class WorkflowInputReader:
    def parse_event(self) -> PipelineEvent:
        key = os.environ.get("TICKET_KEY")
        stage_str = os.environ.get("A2SDLC_TRIGGER_STAGE", "spec")
        if not key:
            raise SkipEvent("TICKET_KEY not set — not in dispatcher-triggered run")
        try:
            stage = StageName(stage_str.lower())
        except ValueError:
            raise SkipEvent(f"unknown trigger stage {stage_str!r}") from None
        return PipelineEvent(key=key, trigger_stage=stage)

    def get_ticket_body(self, key: str) -> str:
        body = os.environ.get("TICKET_BODY")
        if body is None:
            raise RuntimeError("TICKET_BODY env var not set — dispatcher must populate it")
        return body

    # Tracker write methods — deliberate no-ops. All writebacks in Mode 1 flow
    # through DispatcherEventSubscriber over HTTP. CommentManager calls these
    # as part of the normal engine lifecycle; returning sentinels prevents crashes.
    def create_stage_comment(self, *args, **kwargs) -> str:
        return _SENTINEL_COMMENT_ID

    def update_stage_comment(self, *args, **kwargs) -> None:
        return None

    def finalize_stage_comment(self, *args, **kwargs) -> None:
        return None

    def advance_to_next_stage(self, *args, **kwargs) -> None:
        # Stage advancement in Mode 1 is driven by the dispatcher, not by the
        # engine writing labels back to the tracker. The dispatcher fires a
        # fresh workflow for the next stage after a successful stage_completed.
        return None

    def mark_blocked(self, *args, **kwargs) -> None:
        return None

    def mark_done(self, *args, **kwargs) -> None:
        return None
```

Verification note: after implementing, run `uv run --package a2sdlc-engine pytest packages/engine/tests` to confirm nothing in the existing suite regresses. If the engine invokes a WorkAdapter method not listed above, add it as a no-op — do NOT raise — and file a post-demo task to route it through a subscriber.

- [ ] **Step 5: Run — expect PASS**

```bash
uv run --package a2sdlc-engine pytest packages/engine/tests/adapters/work/test_workflow_input.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/engine/src/a2sdlc/adapters/work/workflow_input.py packages/engine/tests/adapters/work/test_workflow_input.py
git commit -m "feat(engine): WorkflowInputReader — WorkAdapter for Mode 1"
```

### Task 4.2: `DispatcherEventSubscriber` — progress → dispatcher

**Files:**
- Create: `packages/engine/src/a2sdlc/adapters/subscriber/dispatcher_event.py`
- Test: `packages/engine/tests/adapters/subscriber/test_dispatcher_event.py`

- [ ] **Step 1: Write failing test**

```python
# packages/engine/tests/adapters/subscriber/test_dispatcher_event.py
import asyncio
from unittest.mock import MagicMock
import httpx
import pytest
from a2sdlc.adapters.subscriber.dispatcher_event import DispatcherEventSubscriber
from a2sdlc.domain.progress import Metrics, StageEnd, StageStart
from a2sdlc.domain.models import StageName


class FakeHttp:
    def __init__(self):
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})

        class R:
            status_code = 202

            def raise_for_status(self_):
                pass

        return R()


@pytest.mark.asyncio
async def test_stage_start_posts_stage_started():
    http = FakeHttp()
    sub = DispatcherEventSubscriber(
        dispatcher_url="https://d.example",
        run_id="r1",
        run_hmac="tok",
        http=http,
    )
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="s1", started_at=0.0))
    # Exactly one POST — stage_started. No run_started emitted by the engine;
    # the dispatcher itself flips "Ready → In Progress" on the first stage_started it sees.
    assert len(http.calls) == 1
    body = http.calls[0]["json"]
    assert body["kind"] == "stage_started"
    assert body["stage"] == "spec"
    assert http.calls[0]["headers"]["Authorization"] == "Bearer tok"
    assert http.calls[0]["url"] == "https://d.example/runs/r1/events"


@pytest.mark.asyncio
async def test_stage_start_never_emits_run_started():
    http = FakeHttp()
    sub = DispatcherEventSubscriber(
        dispatcher_url="https://d.example",
        run_id="r1",
        run_hmac="tok",
        http=http,
    )
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="s1", started_at=0.0))
    await sub.handle(StageStart(stage=StageName.IMPLEMENT, session_id="s1", started_at=1.0))
    kinds = [c["json"]["kind"] for c in http.calls]
    assert "run_started" not in kinds
    assert kinds == ["stage_started", "stage_started"]


@pytest.mark.asyncio
async def test_stage_end_failure_posts_stage_completed_failed():
    http = FakeHttp()
    sub = DispatcherEventSubscriber(
        dispatcher_url="https://d.example",
        run_id="r1",
        run_hmac="tok",
        http=http,
    )
    await sub.handle(
        StageEnd(
            stage=StageName.IMPLEMENT,
            success=False,
            error="boom",
            final_metrics=Metrics(0, 0, 0.0, 0, 0.0),
        )
    )
    body = http.calls[0]["json"]
    assert body["kind"] == "stage_completed"
    assert body["ok"] is False
    assert body["summary"] == "boom"


@pytest.mark.asyncio
async def test_http_failure_is_swallowed():
    class BadHttp:
        def post(self, *a, **kw):
            raise httpx.ConnectError("no route")

    sub = DispatcherEventSubscriber(
        dispatcher_url="https://d.example",
        run_id="r1",
        run_hmac="tok",
        http=BadHttp(),
    )
    # Must not raise — dispatcher outage cannot break the pipeline.
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="s1", started_at=0.0))
```

- [ ] **Step 2: Run — expect FAIL**

```bash
uv run --package a2sdlc-engine pytest packages/engine/tests/adapters/subscriber/test_dispatcher_event.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `dispatcher_event.py`**

```python
"""DispatcherEventSubscriber — POSTs engine progress events to the dispatcher.

Activates only when DISPATCHER_URL is set. Swallows network failures so the
dispatcher being down cannot break the pipeline (MLflow + console still
capture the run).
"""
from __future__ import annotations

import logging
from typing import Any

from a2sdlc.domain.progress import (
    Metrics,
    Milestone,
    ProgressEvent,
    StageEnd,
    StageStart,
    ToolEntry,
)

logger = logging.getLogger(__name__)


class DispatcherEventSubscriber:
    def __init__(
        self,
        *,
        dispatcher_url: str,
        run_id: str,
        run_hmac: str,
        http: Any,
    ) -> None:
        self._url = dispatcher_url.rstrip("/")
        self._run_id = run_id
        self._hmac = run_hmac
        self._http = http

    async def handle(self, event: ProgressEvent) -> None:
        payload = self._translate(event)
        if payload is None:
            return
        try:
            r = self._http.post(
                f"{self._url}/runs/{self._run_id}/events",
                json=payload,
                headers={"Authorization": f"Bearer {self._hmac}"},
                timeout=10.0,
            )
            if hasattr(r, "raise_for_status"):
                r.raise_for_status()
        except Exception as e:  # noqa: BLE001 — intentional: swallow network failures
            logger.warning("dispatcher POST failed (event=%s): %s", payload.get("kind"), e)

    def _translate(self, event: ProgressEvent) -> dict | None:
        # CRITICAL: do NOT emit run_started from the engine. The engine runs
        # once per stage in its own CI process — "first stage_started" per
        # run_id is dedupe'd by the dispatcher, which flips Ready → In Progress
        # exactly once. Emitting run_started here would double-transition.
        if isinstance(event, StageStart):
            return {"kind": "stage_started", "stage": event.stage.value}
        if isinstance(event, StageEnd):
            return {
                "kind": "stage_completed",
                "stage": event.stage.value,
                "ok": event.success,
                "summary": event.error,
            }
        if isinstance(event, (Metrics, Milestone, ToolEntry)):
            # Not forwarded — too chatty. MLflow captures these already.
            return None
        return None
```

Note: in v1 we don't emit `pr_opened` / `pr_updated` / `run_completed` from here because those aren't native `ProgressEvent` types. The dispatcher drives the "In Review" transition off `stage_completed(stage="merge", ok=True)`. Post-demo, add a small extension event (or reuse `Milestone`) to signal richer PR transitions.

- [ ] **Step 4: Run — expect PASS**

```bash
uv run --package a2sdlc-engine pytest packages/engine/tests/adapters/subscriber/test_dispatcher_event.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/engine/src/a2sdlc/adapters/subscriber/dispatcher_event.py packages/engine/tests/adapters/subscriber/test_dispatcher_event.py
git commit -m "feat(engine): DispatcherEventSubscriber — progress → dispatcher over HTTP"
```

### Task 4.3: Wire dispatcher-mode composition in CLI

**Files:**
- Modify: `packages/engine/src/a2sdlc/cli/dispatch.py`

- [ ] **Step 1: Guard existing GitHubWorkAdapter construction behind dispatcher-mode check**

Refactor the top of `dispatch_command` so that in dispatcher mode we never construct `GitHubWorkAdapter` (which requires a valid `GITHUB_REPOSITORY` + PyGithub auth) nor `GitHubReviewAdapter` (same reason). Replace the existing block:

```python
from github import Github  # noqa: PLC0415
from a2sdlc.adapters.review import GitHubReviewAdapter  # noqa: PLC0415
from a2sdlc.adapters.work import GitHubWorkAdapter  # noqa: PLC0415

token = os.environ.get("GITHUB_TOKEN", os.environ.get("GH_TOKEN", ""))
repo_name = os.environ.get("GITHUB_REPOSITORY", "")
repo = Github(token).get_repo(repo_name)
work_adapter = GitHubWorkAdapter(repo)
review_adapter = GitHubReviewAdapter(repo)
```

with:

```python
# Mode selection is ambient — DISPATCHER_URL tells us we're Jira-dispatcher driven,
# GITHUB_ACTIONS tells us we're GH-native. Compose adapters accordingly. Local/eval
# paths are unaffected because `dispatch_command` is not the local entry point.
dispatcher_url = os.environ.get("DISPATCHER_URL")
dispatcher_sub = None

if dispatcher_url:
    from a2sdlc.adapters.work.workflow_input import WorkflowInputReader  # noqa: PLC0415
    from a2sdlc.adapters.subscriber.dispatcher_event import (  # noqa: PLC0415
        DispatcherEventSubscriber,
    )
    import httpx  # noqa: PLC0415

    work_adapter = WorkflowInputReader()  # type: ignore[assignment]
    # In dispatcher mode the engine does not interact with the code host
    # outside of git pushes + PR creation — those use the ambient GITHUB_TOKEN
    # of the GH Actions job. We still need a review adapter; use the GitHub one
    # since the PR lives on GitHub.
    from github import Github  # noqa: PLC0415
    from a2sdlc.adapters.review import GitHubReviewAdapter  # noqa: PLC0415

    token = os.environ["GITHUB_TOKEN"]
    repo_name = os.environ["GITHUB_REPOSITORY"]
    review_adapter = GitHubReviewAdapter(Github(token).get_repo(repo_name))

    run_id = os.environ["RUN_ID"]
    run_hmac = os.environ["RUN_HMAC"]
    http = httpx.Client(timeout=30.0)
    dispatcher_sub = DispatcherEventSubscriber(
        dispatcher_url=dispatcher_url,
        run_id=run_id,
        run_hmac=run_hmac,
        http=http,
    )
else:
    # Mode 2 (or legacy CI) — GH-native composition, unchanged.
    from github import Github  # noqa: PLC0415
    from a2sdlc.adapters.review import GitHubReviewAdapter  # noqa: PLC0415
    from a2sdlc.adapters.work import GitHubWorkAdapter  # noqa: PLC0415

    token = os.environ.get("GITHUB_TOKEN", os.environ.get("GH_TOKEN", ""))
    repo_name = os.environ.get("GITHUB_REPOSITORY", "")
    repo = Github(token).get_repo(repo_name)
    work_adapter = GitHubWorkAdapter(repo)
    review_adapter = GitHubReviewAdapter(repo)
```

- [ ] **Step 2: Subscribe the dispatcher subscriber after `progress_state` is built**

Find the line `progress_state = build_progress_state(root, config.adapters.progress)` and add immediately after:

```python
if dispatcher_sub is not None:
    progress_state.subscribe(dispatcher_sub)
```

- [ ] **Step 3: Skip `GhCommentSubscriber` in dispatcher mode**

The existing `DispatchContext` sets `make_comment_subscriber=lambda comment: GhCommentSubscriber(comment, progress_state)`. In dispatcher mode, that lambda would wire a Jira-unaware GH commenter onto a CommentManager that is writing through `WorkflowInputReader`'s no-op stubs — harmless but noisy. Replace the `make_comment_subscriber` assignment with:

```python
if dispatcher_url:
    # Dispatcher mode: progress is already routed to Jira via DispatcherEventSubscriber.
    # CommentManager still exists but its comment operations are no-ops.
    def _noop_comment_subscriber(comment):
        from a2sdlc.adapters.subscriber import ConsoleSubscriber  # noqa: PLC0415
        return ConsoleSubscriber(progress_state)
    make_comment_subscriber = _noop_comment_subscriber
else:
    def _gh_comment_subscriber(comment):
        from a2sdlc.adapters.subscriber.gh_comment import GhCommentSubscriber  # noqa: PLC0415
        return GhCommentSubscriber(comment, progress_state)
    make_comment_subscriber = _gh_comment_subscriber
```

Then pass `make_comment_subscriber=make_comment_subscriber` to `DispatchContext(...)`.

- [ ] **Step 2: Run engine tests**

```bash
uv run --package a2sdlc-engine pytest packages/engine/tests -v
```

Expected: all existing engine tests still PASS; no new failures.

- [ ] **Step 3: Commit**

```bash
git add packages/engine/src/a2sdlc/cli/dispatch.py
git commit -m "feat(engine): wire dispatcher-mode composition in CLI dispatch"
```

---

## Phase 5: Reusable workflow + target-repo example

### Task 5.1: Create `run-split.yml` reusable workflow

**Files:**
- Create: `.github/workflows/run-split.yml`
- Create: `docs/mode1/example-workflows/a2sdlc-split.yml`

- [ ] **Step 1: Write `.github/workflows/run-split.yml`**

```yaml
# .github/workflows/run-split.yml
# Reusable workflow: engine run for Mode 1 (Jira dispatcher).
# Inputs are set by the dispatcher's workflow_dispatch call.

name: a2sdlc — run (split)

on:
  workflow_call:
    inputs:
      ticket_key:     { required: true,  type: string }
      run_id:         { required: true,  type: string }
      run_hmac:       { required: true,  type: string }
      dispatcher_url: { required: true,  type: string }
      base_branch:    { required: false, type: string, default: main }
      ticket_body:    { required: false, type: string, default: "" }
      trigger_stage:  { required: false, type: string, default: "spec" }
    secrets:
      ANTHROPIC_API_KEY:
        required: true
      MLFLOW_TRACKING_URI:
        required: false
      MLFLOW_TRACKING_USERNAME:
        required: false
      MLFLOW_TRACKING_PASSWORD:
        required: false

jobs:
  engine:
    runs-on: ubuntu-latest
    timeout-minutes: 60
    permissions:
      contents: write
      pull-requests: write
    env:
      TICKET_KEY:              ${{ inputs.ticket_key }}
      TICKET_BODY:             ${{ inputs.ticket_body }}
      RUN_ID:                  ${{ inputs.run_id }}
      RUN_HMAC:                ${{ inputs.run_hmac }}
      DISPATCHER_URL:          ${{ inputs.dispatcher_url }}
      A2SDLC_TRIGGER_STAGE:    ${{ inputs.trigger_stage }}
      BASE_BRANCH:             ${{ inputs.base_branch }}
      GITHUB_TOKEN:            ${{ github.token }}
      ANTHROPIC_API_KEY:       ${{ secrets.ANTHROPIC_API_KEY }}
      MLFLOW_TRACKING_URI:     ${{ secrets.MLFLOW_TRACKING_URI }}
      MLFLOW_TRACKING_USERNAME: ${{ secrets.MLFLOW_TRACKING_USERNAME }}
      MLFLOW_TRACKING_PASSWORD: ${{ secrets.MLFLOW_TRACKING_PASSWORD }}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
          ref: ${{ inputs.base_branch }}
      - uses: astral-sh/setup-uv@v4
      - name: Install engine
        run: |
          uv tool install --from 'git+https://github.com/yoselabs/a2sdlc-engine@main' a2sdlc-engine
      - name: Dispatch
        run: uv tool run a2sdlc dispatch
```

- [ ] **Step 2: Write `docs/mode1/example-workflows/a2sdlc-split.yml`**

```yaml
# .github/workflows/a2sdlc-split.yml (in the TARGET repo)
name: a2sdlc-split

on:
  workflow_dispatch:
    inputs:
      ticket_key:     { required: true,  type: string }
      run_id:         { required: true,  type: string }
      run_hmac:       { required: true,  type: string }
      dispatcher_url: { required: true,  type: string }
      base_branch:    { required: false, type: string, default: main }
      ticket_body:    { required: false, type: string, default: "" }
      trigger_stage:  { required: false, type: string, default: "spec" }

jobs:
  engine:
    uses: yoselabs/a2sdlc-engine/.github/workflows/run-split.yml@main
    with:
      ticket_key:     ${{ inputs.ticket_key }}
      run_id:         ${{ inputs.run_id }}
      run_hmac:       ${{ inputs.run_hmac }}
      dispatcher_url: ${{ inputs.dispatcher_url }}
      base_branch:    ${{ inputs.base_branch }}
      ticket_body:    ${{ inputs.ticket_body }}
      trigger_stage:  ${{ inputs.trigger_stage }}
    secrets:
      ANTHROPIC_API_KEY:        ${{ secrets.ANTHROPIC_API_KEY }}
      MLFLOW_TRACKING_URI:      ${{ secrets.MLFLOW_TRACKING_URI }}
      MLFLOW_TRACKING_USERNAME: ${{ secrets.MLFLOW_TRACKING_USERNAME }}
      MLFLOW_TRACKING_PASSWORD: ${{ secrets.MLFLOW_TRACKING_PASSWORD }}
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/run-split.yml docs/mode1/example-workflows/a2sdlc-split.yml
git commit -m "ci: reusable run-split.yml + target-repo example for Mode 1"
```

---

## Phase 6: Shaping skill — Jira mode

### Task 6.1: Scaffold `shaping-jira` skill

**Files:**
- Create: `skills/shaping-jira/SKILL.md`
- Create: `skills/shaping-jira/templates/pitch.md`

- [ ] **Step 1: Write `skills/shaping-jira/SKILL.md`**

```markdown
---
name: shaping-jira
description: Shape a feature milestone into a Jira epic + dependency-linked stories. Input: a Confluence page (via a2atlassian MCP) or a local markdown brief. Output: an epic issue plus stories linked by 'is blocked by', with the first root story transitioned to Ready so the a2sdlc dispatcher kicks off the engine.
---

# Shaping (Jira mode)

## When to use

- User has requirements in Confluence or a brief and wants Jira tickets
  ordered by dependency, ready for the a2sdlc engine to pick up.
- Target Jira project is already configured in the dispatcher's PROJECTS_JSON.
- a2atlassian MCP is connected with a Jira user that can create issues,
  link them, and transition them.

## Flow

1. Read the input source:
   - Confluence: `mcp__a2atlassian__confluence_get_page` (or equivalent from
     the a2atlassian server's Confluence tool list) with the page id/slug.
   - Local markdown: use Read tool.
2. Ask the user clarifying questions one at a time — scope, non-goals,
   success criteria. Short, targeted. Don't restart full brainstorming.
3. Draft a pitch list as markdown (see `templates/pitch.md`). Each pitch has
   - title
   - description (2–3 sentences)
   - acceptance criteria (bulleted)
   - an ordered dependency list referring to earlier pitch slugs.
4. Present draft back to user. Iterate.
5. On approval:
   a. Create epic via `mcp__a2atlassian__jira_create_issue` with
      issue_type=Epic, record its key.
   b. For each pitch, create a Story issue linked to the epic
      (fields: customfield_10014 or `Epic Link` depending on instance —
      consult a2atlassian MCP docs; fall back to issue link type "Relates to
      epic" if the custom field is unavailable).
   c. After all stories exist and slug→key mapping is known, for each story
      with dependencies, create `is blocked by` links via
      `mcp__a2atlassian__jira_create_issue_link`.
   d. Transition the root stories (no blockers) to the project's
      `status_ready` value via `mcp__a2atlassian__jira_transition_issue`.

## Anti-patterns

- Do not create Jira issues before the user approves the draft.
- Do not manually trigger the dispatcher — transitioning to Ready fires the
  Jira webhook automatically.
- Do not invent status names — use what's configured in dispatcher's
  PROJECTS_JSON for this project. When unsure, ask.

## Observability

Every ticket's life is visible in three places after shaping:
- Jira ticket: comments from the engine via the dispatcher.
- GH Actions run page linked from the Jira comment.
- MLflow run tagged with `ticket_key` (if MLflow is configured).
```

- [ ] **Step 2: Write `skills/shaping-jira/templates/pitch.md`**

```markdown
# <story title>

## Description
<2-3 sentences describing the concrete problem this story solves.>

## Acceptance criteria
- [ ] <criterion 1>
- [ ] <criterion 2>

## Blocked by
- <slug of earlier pitch> (will resolve to Jira key at creation time)
```

- [ ] **Step 3: Commit**

```bash
git add skills/shaping-jira/
git commit -m "feat(skills): shaping-jira — Confluence + a2atlassian MCP skill"
```

---

## Phase 7: Dockerfiles + Dokploy compose

### Task 7.1: Dockerfile.engine

**Files:**
- Create: `Dockerfile.engine`

- [ ] **Step 1: Write `Dockerfile.engine`**

```dockerfile
# Dockerfile.engine — builds an image running `a2sdlc dispatch`.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl \
 && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages/engine ./packages/engine
RUN uv sync --package a2sdlc-engine --no-dev --frozen

ENTRYPOINT ["uv", "run", "--package", "a2sdlc-engine", "--no-dev", "a2sdlc"]
CMD ["dispatch"]
```

- [ ] **Step 2: Build-verify**

```bash
docker build -f Dockerfile.engine -t a2sdlc-engine:dev .
docker run --rm a2sdlc-engine:dev --help
```

Expected: engine CLI help prints.

- [ ] **Step 3: Commit**

```bash
git add Dockerfile.engine
git commit -m "chore(docker): Dockerfile.engine (engine-only image)"
```

### Task 7.2: Dockerfile.dispatcher

**Files:**
- Create: `Dockerfile.dispatcher`

- [ ] **Step 1: Write `Dockerfile.dispatcher`**

```dockerfile
# Dockerfile.dispatcher — FastAPI service on uvicorn.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
 && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages/dispatcher ./packages/dispatcher
RUN uv sync --package a2sdlc-dispatcher --no-dev --frozen

EXPOSE 8000
ENTRYPOINT ["uv", "run", "--package", "a2sdlc-dispatcher", "--no-dev", "a2sdlc-dispatcher"]
```

- [ ] **Step 2: Build + run healthz**

```bash
docker build -f Dockerfile.dispatcher -t a2sdlc-dispatcher:dev .
docker run --rm -d --name dsp -p 8000:8000 \
  -e JIRA_BASE_URL=https://example.atlassian.net \
  -e JIRA_USER=bot \
  -e JIRA_TOKEN=x \
  -e GH_APP_ID=1 \
  -e GH_APP_PRIVATE_KEY=dummy \
  -e GH_APP_INSTALLATION_ID=1 \
  -e HMAC_SIGNING_KEY=k$(printf 'k%.0s' {1..31}) \
  -e SELF_URL=http://localhost:8000 \
  -e PROJECTS_JSON='[]' \
  a2sdlc-dispatcher:dev
sleep 2
curl -sSf http://localhost:8000/healthz
docker rm -f dsp
```

Expected: `{"status":"ok"}`.

- [ ] **Step 3: Commit**

```bash
git add Dockerfile.dispatcher
git commit -m "chore(docker): Dockerfile.dispatcher (dispatcher-only image)"
```

### Task 7.3: Dokploy compose

**Files:**
- Create: `deploy/dokploy/docker-compose.yml`
- Create: `deploy/dokploy/README.md`

- [ ] **Step 1: Write `deploy/dokploy/docker-compose.yml`**

```yaml
# Dokploy compose for the a2sdlc dispatcher.
# Assumes external Traefik network `traefik-public` and a Cloudflare
# wildcard DNS record for `*.yose.tld` pointing at Dokploy host.

services:
  dispatcher:
    image: ghcr.io/yoselabs/a2sdlc-dispatcher:main
    restart: unless-stopped
    environment:
      JIRA_BASE_URL:              ${JIRA_BASE_URL}
      JIRA_USER:                  ${JIRA_USER}
      JIRA_TOKEN:                 ${JIRA_TOKEN}
      GH_APP_ID:                  ${GH_APP_ID}
      GH_APP_PRIVATE_KEY:         ${GH_APP_PRIVATE_KEY}
      GH_APP_INSTALLATION_ID:     ${GH_APP_INSTALLATION_ID}
      HMAC_SIGNING_KEY:           ${HMAC_SIGNING_KEY}
      JIRA_WEBHOOK_SECRET:        ${JIRA_WEBHOOK_SECRET}
      GH_WEBHOOK_SECRET:          ${GH_WEBHOOK_SECRET}
      DOKPLOY_DEPLOY_TOKEN:       ${DOKPLOY_DEPLOY_TOKEN}
      PROJECTS_JSON:              ${PROJECTS_JSON}
      SELF_URL:                   ${SELF_URL}
    networks:
      - traefik-public
    labels:
      traefik.enable: "true"
      traefik.http.routers.a2sdlc-dispatcher.rule: "Host(`dispatcher.yose.tld`)"
      traefik.http.routers.a2sdlc-dispatcher.entrypoints: "websecure"
      traefik.http.routers.a2sdlc-dispatcher.tls: "true"
      traefik.http.routers.a2sdlc-dispatcher.tls.certresolver: "cloudflare"
      traefik.http.services.a2sdlc-dispatcher.loadbalancer.server.port: "8000"

networks:
  traefik-public:
    external: true
```

- [ ] **Step 2: Write `deploy/dokploy/README.md`**

```markdown
# a2sdlc dispatcher — Dokploy deploy

## Prereqs

- Dokploy installed on the host, Traefik running with an external network
  named `traefik-public`.
- Cloudflare wildcard DNS record for the chosen domain (`dispatcher.yose.tld`).
- GitHub App registered in the yoselabs org, installed on target repos.
- Jira Cloud bot user + API token.
- Self-hosted MLflow reachable from GitHub Actions (optional).

## Env (set in Dokploy UI)

| Var | Meaning |
|---|---|
| `JIRA_BASE_URL` | e.g. `https://acme.atlassian.net` |
| `JIRA_USER` | bot account email |
| `JIRA_TOKEN` | API token |
| `GH_APP_ID` | numeric App id |
| `GH_APP_PRIVATE_KEY` | PEM contents, newlines preserved |
| `GH_APP_INSTALLATION_ID` | numeric installation id (per target-repo-owning org). Dispatcher mints JWT + exchanges for installation tokens on demand; no long-lived token to rotate. |
| `HMAC_SIGNING_KEY` | random 32 bytes, base64 or hex |
| `JIRA_WEBHOOK_SECRET` | shared secret for webhook sig verification |
| `GH_WEBHOOK_SECRET` | shared secret for GH webhook sig verification |
| `SELF_URL` | public HTTPS URL of this dispatcher, e.g. `https://dispatcher.yose.tld`. Used as `dispatcher_url` workflow input. |
| `PROJECTS_JSON` | JSON array, one entry per Jira project (see spec §"Config") |

## Deploy

1. Point Dokploy at this compose (repo + path).
2. Set env vars.
3. Deploy. Traefik will serve HTTPS on `https://dispatcher.yose.tld/healthz`.

## Configure Jira webhook

Jira → Project settings → Automation → System webhook.
- URL: `https://dispatcher.yose.tld/jira/events`
- Secret: `JIRA_WEBHOOK_SECRET`
- Events: Issue updated (scoped to the project)
- Payload: default JSON

## Configure GitHub webhook

Each target repo's GitHub App installation auto-sends PR events to a shared
URL. If using a webhook directly instead of the App:
- URL: `https://dispatcher.yose.tld/gh/events`
- Secret: `GH_WEBHOOK_SECRET`
- Content-Type: `application/json`
- Events: Pull request (closed)
```

- [ ] **Step 3: Commit**

```bash
git add deploy/dokploy/
git commit -m "chore(deploy): Dokploy compose + runbook for dispatcher"
```

---

## Phase 8: End-to-end smoke test + docs

### Task 8.1: Onboarding doc for Mode 1

**Files:**
- Create: `docs/mode1/README.md`

- [ ] **Step 1: Write `docs/mode1/README.md`**

```markdown
# a2sdlc — Jira + GitHub runtime (Mode 1)

End-to-end: Confluence requirements → shaping skill → Jira epic + stories
linked by "is blocked by" → dispatcher fires engine in your repo's GH
Actions → PR opens → human merges → dispatcher transitions Jira and
unblocks the next story.

## What you install

### In the dispatcher (Dokploy)

See `deploy/dokploy/README.md`.

### In each target repo

1. Copy `docs/mode1/example-workflows/a2sdlc-split.yml` →
   `.github/workflows/a2sdlc-split.yml`.
2. Repo secrets:
   - `ANTHROPIC_API_KEY` (required)
   - `MLFLOW_*` (optional)
3. Ensure the yoselabs GitHub App is installed on this repo with
   `actions: write`, `contents: write`, `pull_requests: write`.

No Jira creds in the repo. No mapping file.

## Driving it

1. In Claude Code Desktop, invoke the `shaping-jira` skill against a
   Confluence page or brief.
2. Skill creates an epic + stories with "is blocked by" links, transitions
   the root story to `Ready`.
3. Dispatcher receives Jira webhook, triggers `a2sdlc-split.yml` on the
   target repo with `run_id` + `run_hmac` + `ticket_body` in the inputs.
4. Engine runs SPEC → IMPLEMENT → REVIEW → MERGE, posting progress events
   to the dispatcher, which comments/transitions Jira.
5. Engine opens PR with `Closes JIRA-KEY`.
6. You merge the PR. GitHub webhook → dispatcher → Jira ticket → Done.
7. Dispatcher transitions any fully-unblocked dependents to `Ready`. Cycle
   repeats until the epic is complete.

## Observability

- Jira ticket comments with the GH Actions run URL and (if MLflow set)
  MLflow run URL.
- GH Actions run page — live logs, re-run button.
- MLflow — structured trace per run, tagged with `ticket_key`, `run_id`,
  `branch`, `variant`, `mode=jira-dispatcher`.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Jira ticket sits in Ready, no workflow fires | Webhook URL wrong; webhook secret mismatch; `JIRA_WEBHOOK_SECRET` env unset on dispatcher |
| Workflow fires but Jira isn't updated | `DISPATCHER_URL` not passed into workflow; `RUN_HMAC` mismatch (regenerate) |
| PR merges but dependents stuck Blocked | `Closes <KEY>` missing from PR body; issue links not `is blocked by` |
| Dispatcher 401 on `/runs/{id}/events` | Token expired (>24h) or wrong signing key |
```

- [ ] **Step 2: Commit**

```bash
git add docs/mode1/README.md
git commit -m "docs: Mode 1 onboarding README"
```

### Task 8.2: End-to-end smoke test

**Files:**
- Create: `docs/mode1/smoke-test.md` (written after the run)

- [ ] **Step 1: Prepare a throwaway Jira project + GH repo**

- Create or pick a Jira project with key `DEMO`.
- Create workflow statuses `Ready`, `In Progress`, `In Review`, `Done`, `Blocked`.
- Create or pick a GH repo `iorlas/a2sdlc-demo1-client` with Actions enabled.
- Install the yoselabs GitHub App on it.
- Add secret `ANTHROPIC_API_KEY` (+ optional `MLFLOW_*`) in repo settings.
- Add `.github/workflows/a2sdlc-split.yml` from `docs/mode1/example-workflows/`.

- [ ] **Step 2: Configure the dispatcher**

- Deploy to Dokploy per `deploy/dokploy/README.md`.
- `PROJECTS_JSON` contains one entry mapping `DEMO` → `iorlas/a2sdlc-demo1-client`.
- Configure the Jira webhook on the DEMO project pointing at
  `https://dispatcher.yose.tld/jira/events` with the shared secret.

- [ ] **Step 3: Run the shaping skill**

- Create a tiny Confluence page or local brief: "Build a FizzBuzz HTTP
  endpoint; second story adds a counter."
- Invoke `shaping-jira` against the input, approve the draft.
- Expect: epic `DEMO-1`, stories `DEMO-2` and `DEMO-3` linked, `DEMO-2`
  transitioned to Ready.

- [ ] **Step 4: Watch the pipeline**

- Dispatcher logs show the `workflow_dispatch` call.
- GH Actions page shows `a2sdlc-split.yml` running.
- Jira `DEMO-2` receives comments: "Run started", "Entering stage: spec",
  etc.
- Engine opens a PR with `Closes DEMO-2`.
- Merge the PR.
- `DEMO-2` transitions to Done. `DEMO-3` transitions to Ready.
- New `a2sdlc-split.yml` run starts for `DEMO-3` automatically.

- [ ] **Step 5: Record findings in `docs/mode1/smoke-test.md`**

Capture what worked, what broke, and any configuration gotchas. Commit.

### Task 8.3: Final gate + PR

**Files:** No new files.

- [ ] **Step 1: Run the gate**

```bash
make check
```

Expected: all green. If the workspace split interfered with `lint-imports`, fix import-linter config before proceeding.

- [ ] **Step 2: Open the PR**

```bash
git push -u origin feat/jira-dispatcher
gh pr create --title "feat: Jira dispatcher (Mode 1)" --body "$(cat <<'EOF'
## Summary
- New `packages/dispatcher/` FastAPI service with `/jira/events`, `/gh/events`, `/runs/{run_id}/events` endpoints.
- Engine additions: `WorkflowInputReader` (input) + `DispatcherEventSubscriber` (output), both env-gated on `DISPATCHER_URL`.
- New reusable workflow `run-split.yml` + target-repo example.
- `shaping-jira` skill using a2atlassian MCP.
- Dockerfile.engine + Dockerfile.dispatcher split; Dokploy compose with Traefik TLS.
- Onboarding docs (`docs/mode1/README.md`) + smoke-test findings (`docs/mode1/smoke-test.md`).

## Test plan
- [x] All new unit tests pass (`make check`)
- [ ] Smoke test run: 2 linked Jira stories, engine picks up each, PRs merge, dependents unblock
- [ ] Jira comments show MLflow link per run
- [ ] Dispatcher withstands one simulated Jira API timeout without losing the run

Depends on: Plan A (GH-native runtime) merged.
EOF
)"
```

---

## Spec coverage

Cross-reference against `docs/superpowers/specs/2026-04-19-shaping-and-dispatcher-design.md` §"Days 2–3 — Jira Dispatcher (Mode 1)":

| Spec item | Task(s) |
|---|---|
| New `packages/dispatcher/` FastAPI service | Task 0.3 + Phase 1–3 |
| `POST /jira/events` | Task 3.3 |
| `POST /gh/events` | Task 3.5 |
| `POST /runs/{run_id}/events` | Task 3.4 |
| `GET /healthz` | Task 0.3 |
| `PROJECTS_JSON` env config (Pydantic parsed) | Task 1.3 |
| Per-run HMAC capability token (24h) | Task 1.2 |
| In-memory runs table | Task 1.4 |
| Domain event Pydantic models | Task 1.1 |
| Jira adapter: comment, transition, blocker queries | Task 2.1 |
| Event → Jira translator | Task 2.2 |
| Engine `WorkflowInputReader` (input) | Task 4.1 |
| Engine `DispatcherEventSubscriber` (output) | Task 4.2 |
| Env-driven composition wiring | Task 4.3 |
| `run-split.yml` reusable workflow | Task 5.1 |
| Target-repo example workflow | Task 5.1 |
| `shaping-jira` skill with a2atlassian MCP | Task 6.1 |
| `Dockerfile.engine` | Task 7.1 |
| `Dockerfile.dispatcher` | Task 7.2 |
| Dokploy compose + Traefik labels | Task 7.3 |
| Onboarding doc | Task 8.1 |
| Smoke test | Task 8.2 |

Spec items explicitly deferred (post-demo):
- Parallel A/B variant matrix orchestration from Jira (workflow-level matrix is possible today, but not wired from dispatcher in v1).
- GitLab / Azure Boards adapters.
- Admin UI over `PROJECTS_JSON`.
- Marketplace publication.
- OIDC token exchange replacing HMAC.
- YAML/SQLite projects store.
- Dokploy deploy API trigger on epic-complete (noted in spec; add in follow-up if demo needs it — just adds one httpx call from the unblock path).
- `pr_opened` / `pr_updated` / `run_completed` events (deferred inside Task 4.2 — add in post-demo pass once the engine exposes PR-level Milestone events).
