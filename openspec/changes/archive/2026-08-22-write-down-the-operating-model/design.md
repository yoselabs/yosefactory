Motivation: see [proposal.md](proposal.md).

## Context

Checked against disk before writing anything (Article XII):

- `grep -ci openspec CLAUDE.md AGENTS.md` → 0, 0; `grep -c "Article [IVX]" both` → 0, 0 — confirmed
  the diagnosis before acting on it.
- `openspec/config.yaml`'s `context` block already states "explore does not authorize building" in
  full prose — confirmed by reading it, not assumed from the dispatch's summary.
- `openspec/config.yaml`'s `operations.archive.guidance` already states the ADR obligation and its
  non-obvious test, put there by the precedent change `close-the-adr-gap` (archived 2026-08-22) —
  the same seam this change points at rather than restates.
- `CLAUDE.md`'s Stack "Model:" line dates to `66b885f1`, 2026-08-12 (`git blame`); `decisions/0006`
  is dated 2026-08-20 and its `Context` section states it as "Denis's ruling" — both name the same
  subject (the model `claude-agent-sdk` invokes as this platform's harness), so this is a genuine
  contradiction, not two statements about different things. Nothing under `src/` reads `CLAUDE.md`.
- K's D022 (`decisions/D022-the-platform-is-the-machine-and-it-may-push.md`) grants push to "the
  platform" — `runtime/turn.py`'s `commit()`/`take_turn` — explicitly, with a stated scope table
  (`may` / `may not` / `when` / `on failure`). It is not a grant to a build/worker session.
- `AGENTS.md`'s only over-disclosing path (the operator's personal memory-system path in the
  "Override" note) sits inside the `BEGIN/END BEADS CODEX SETUP` managed block — confirmed by
  `grep -n "BEGIN BEADS CODEX\|END BEADS CODEX" AGENTS.md` before deciding it was unfixable in
  place.

## Goals / Non-Goals

**Goals:**
- Make `AGENTS.md` load-bearing for a worker with no director present, not aspirational.
- Keep the constitution itself in exactly one place (K, private) and verify the *reference* from
  the public repo, never generate the reverse.
- Resolve the model contradiction with a checked verdict, not a guess, and leave a durable pointer
  rather than a value that can drift again.
- State the actual commit/push rule where the stale managed-block text is, without editing inside
  a regenerated block.
- Triage every host-shorthand path with a stated reason per item; fix only what needs fixing.

**Non-Goals:**
- A generator mirroring `orchestration.md`'s prose into this repo (explicitly rejected in the
  dispatch — a private-to-public copy machine, and this program already paid for that leak once).
- Restating fleet/dispatch/concurrency articles that govern a director, not a worker's mechanics in
  this repo (Articles I-IV, VI-XIII excluding the retired one — see the closing report for the
  full per-article call).
- Editing inside `AGENTS.md`'s managed beads blocks.
- Any change to `src/` — this is a documentation-and-config change throughout.

## Decisions

**D1 — cite five articles (V, XIV, XV, XVI, XVII), not more.** These are the ones the dispatch
named as examples of worker-mechanics-in-this-repo (commit mechanics, validating, archiving,
receipt, one director) and, checked against the full text, the only ones whose subject is a single
session's own conduct rather than a director's dispatch, a fleet's concurrency, or Denis-facing
escalation. Article XI (index hygiene) is subsumed by V's own text in `orchestration.md`
("Subsumed by Article V on the success path") and is not separately cited, to avoid two citations
for one rule.

**D2 — the drift checker runs under `make check`, not the pre-commit hook.** `.pre-commit-config.yaml`'s
hooks run on every commit, on every clone, including ones with no K checkout — a hook that silently
no-ops most of the time trains a reader to stop noticing when it does. `make check` is invoked
deliberately and prints its skip reason, which is closer to `orchestration.md`'s own "a check that
cannot run is never reported as a pass" standard (borrowed from `forbid-host-paths.py`'s own exit
code discipline, which uses the same distinction).

**D3 — `CLAUDE.md` points at the ADR, states its scope boundary, and gets its own new ADR
(`0009`)** rather than a silent fix. The config.yaml non-obvious test applies directly: a future
worker editing the Stack section could plausibly restore `claude-opus-5` without knowing ADR-0006
exists, because the drift already happened once with nobody noticing for eight days.

**D4 — the AGENTS.md managed-block path is flagged, not edited.** Editing inside
`BEGIN/END BEADS CODEX SETUP` would be silently reverted by the next `bd setup codex` run, which is
a worse outcome than an honest, visible flag: a fix that looks permanent but silently regenerates
away is the exact false-confidence shape this whole change exists to avoid.

## Risks

- The drift checker's regex (`orchestration.md Article <roman>`) is a soft contract with how
  `AGENTS.md` phrases citations. Mitigated by keeping the citation phrasing consistent and the
  checker's own docstring explicit about what it does and does not verify.
- `make check`'s new `citations` target adds one Python invocation to every `check` run. Cost is a
  single file read plus a regex pass over `AGENTS.md` and `orchestration.md`; negligible against
  the existing 59s test suite.
