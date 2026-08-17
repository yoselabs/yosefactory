## 1. Baseline

- [x] 1.1 Record `make check` baseline and `git status --porcelain` before touching anything —
      **cost the disclosure in the proposal's Impact section: this baseline run fired the full live
      suite for real, before gating existed, spending an unrecorded amount. Left as the finding it
      is, not concealed.**
- [x] 1.2 Re-confirm `claude --version` against `PINNED_VERSION` on this machine — `2.1.225`, matches

## 2. The ledger

- [x] 2.1 `src/yosefactory/runtime/spend.py`: `SPEND_LOG` resolved from `Path(__file__)`, matching
      `protocol/backlog.py`'s `VOCABULARY_SPEC` pattern; `record()`; `total_since()`
- [x] 2.2 `executor/claude.py::run()` calls `spend.record()` once, after `usage` is built, before
      returning — unconditionally, including zero-cost runs

## 3. Gating

- [x] 3.1 `pyproject.toml`: registered the `live` marker; `addopts = "-m 'not live'"`
- [x] 3.2 Both integration test files: `pytest.mark.live` added to the existing `pytestmark` list
      alongside the version `skipif`
- [x] 3.3 `Makefile`: `test-live` target (`uv run pytest -q -m live`); comment on `check`/`test`
      states the reason (frequency, not just visibility) so a future simplification does not fold it
      back in
- [x] 3.4 Zero-cost check: `pytest --collect-only -q` → 272/283 collected, 11 deselected;
      `pytest --collect-only -q -m live` → the same 11, exactly the two live files' tests

## 4. Says what it spent

- [x] 4.1 `tests/conftest.py`: `pytest_sessionstart` records session start; `pytest_sessionfinish`
      prints the total from `spend.total_since(start)` when nonzero
- [x] 4.2 Confirmed: `make check` run after wiring produced no ledger file at all (verified
      `ls ledger/spend.jsonl` failed with "No such file" immediately after a green `make check`)

## 5. The one real receipt

- [x] 5.1 Ran exactly one canary: `pytest -q -m live tests/executor/test_integration.py::test_a_real_run_produces_a_structured_outcome`
- [x] 5.2 `ledger/spend.jsonl` gained one row: `{"ts": "2026-08-17T00:15:46.507681+00:00", "run_id":
      "receipt1", "total_cost_usd": 0.04466250000000001}`. Session output: `live spend this session:
      $0.0447 (see ledger/spend.jsonl)` — matches the row.
- [x] 5.3 **Spent by 5.1: $0.0447.** (Baseline in task 1.1 spent an additional, unrecorded amount —
      see disclosure above; that is the failure this change fixes, encountered before the fix landed.)

## 6. Close

- [x] 6.1 `make check` green (272 passed / 11 deselected, 37.77s); confirmed it spends nothing by
      checking `ledger/spend.jsonl` itself with `ls` immediately after a green run, not by inferring
      it from the deselect count — the deselect count would have been the instrument, not the subject
- [x] 6.2 `openspec validate record-live-spend-and-gate-make-check --strict` passed before archiving
- [x] 6.3 Committed `8c7141d`, `git commit -F <file> -- <literal paths>`, `PREK_ALLOW_NO_CONFIG=1`;
      `git diff --cached` confirmed empty after
- [x] 6.4 Archived; `claude-executor/spend-ledger` promoted with `+2, ~0, -0, →0` — nothing MODIFIED,
      nothing deleted; `openspec validate --specs --strict` passes 18/18 afterward
- [x] 6.5 Reported: $0.0447 spent on the one deliberate canary; the row it produced;
      `tail -1 ledger/spend.jsonl` is the "what did this cost" command

## Outcome

**Landed.** `ledger/spend.jsonl` now records every real invocation's cost, joined by `run_id` to the
matching `TurnRecord`; `make check`/`test` no longer reach the live binary at all (`-m 'not live'`
default); `make test-live` runs them deliberately and prints the session's spend.

**The finding this change surfaced is bigger than its dispatch.** The dispatching director's own
claim that `ledger/runs/` already carried `total_cost_usd` was checked against `TurnRecord.to_dict`/
`from_dict` and was false: no run, test or production, had ever had its cost recorded anywhere
durable. `tmp_path` deletion was one more way to lose a number that was already unrecorded, not the
cause.

**The change's own author produced its case study.** This change's baseline `make check` — run
before any gating existed, to get a before/after — fired the full live suite for real: 9 live
invocations, cost unrecorded because the recorder did not exist yet. That is not a footnote; it is
the defect firing one last time, on the person building the fix, measured the same afternoon the fix
landed. **The platform now records what it spends, and it took until the day after it satisfied its
own kill criterion (D014). Every run before commit `8c7141d` — including the a2web commit that
scored it — cost an amount nobody will ever know.**

**Verified by checking the subject, not the instrument.** The gate was confirmed by `ls
ledger/spend.jsonl` failing immediately after a green `make check` — not by reading the deselect
count, which would have shown the same 11 whether or not the file write was actually reachable.

**Total real spend this change:** $0.0447, one canary
(`test_a_real_run_produces_a_structured_outcome`), against a $0.50 budget and a stated preference
for $0. The baseline's unrecorded 9-invocation spend is separate and permanently unknown, by
construction — the exact fact this change exists to make impossible going forward.
