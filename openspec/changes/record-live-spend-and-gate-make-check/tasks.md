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

- [ ] 6.1 `make check` green (confirmed, 272 passed / 11 deselected, 37.77s) and spends nothing
- [ ] 6.2 `openspec validate record-live-spend-and-gate-make-check --strict` passes before archiving
- [ ] 6.3 Commit, `git commit -F <file> -- <literal paths>`, `PREK_ALLOW_NO_CONFIG=1`,
      `git diff --cached` confirmed empty
- [ ] 6.4 Archive; confirm the new capability promotes cleanly (nothing MODIFIED, no deletions)
- [ ] 6.5 Report: dollar figure spent this change, the ledger row it produced, and the exact command
      that reproduces "what did today cost"
