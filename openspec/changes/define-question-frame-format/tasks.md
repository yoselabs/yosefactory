## 1. The directory and its stated format

- [x] 1.1 ~~Create `questions/` with a `.gitkeep`~~ — unnecessary: the directory ships with
      `README.md` and examples, so git tracks it already
- [x] 1.2 Write `questions/README.md`: the record schema (`asked`, `answer`, `timeout`, `nudge`,
      `cancel`, `note`), the common fields, the `qid` format, and the fold rules — the normative
      source is `specs/question-frame/spec.md`, and the README points at it rather than
      restating it loosely
- [x] 1.3 State the seven kinds in the README with their blocking-by-design / blocking-by-failure
      split, and the rule that kind is advisory and never a reason to refuse a question

## 2. Worked examples that carry the acceptance test

- [x] 2.1 Write `questions/examples/q-20260816T171204Z-3f9a2c1d.jsonl` — a `cost-approval`
      question to `denis` with `deadline`, `on_timeout: default:no`, `nudge_at`, `return_to`,
      answered before its deadline
- [x] 2.2 Write `questions/examples/q-20260816T171331Z-b7e40a52.jsonl` — a request with
      `to: loop:shelf`, left `awaiting`, demonstrating that answering 2.1 changed nothing here
- [x] 2.3 Write `questions/examples/q-20260816T171402Z-5c1de9f7.jsonl` — a question that reaches
      its deadline and is closed by a `timeout` record carrying the pre-registered default
- [x] 2.4 Write `questions/examples/q-20260817T080200Z-9ab35e04.jsonl` — a rejected request whose
      `answer` carries `verdict: reject`, a `cause`, and `next: retry`, showing that a no leaves
      somewhere to go
- [x] 2.5 Add `questions/examples/README.md` mapping each file to the spec scenario it
      demonstrates, including the two-branch acceptance test (2.1 answered, 2.2 still awaiting)

## 3. Verify the format against its own rules by hand

- [x] 3.1 Confirm every example line is valid JSON, one record per line, `asked` first
      (`python3 -c` over the files; no test suite is added by this change)
- [x] 3.2 Confirm every record carries `rec`, `qid`, `ts` (RFC3339 UTC), `actor`, and that each
      file's `qid` matches its filename stem
- [x] 3.3 Confirm the fold of each example yields the state its README entry claims, and that
      the answered example's sibling is untouched — the dispatch's acceptance test. Result:
      `3f9a2c1d answered`, `b7e40a52 awaiting`, `5c1de9f7 timed_out`, `9ab35e04 answered`
- [x] 3.4 Confirm no example carries a client name or former-employer reference (public repo)

## 4. Close out

- [x] 4.1 `openspec validate define-question-frame-format --strict` passes
- [x] 4.2 Commit with explicit pathspecs only — `questions/` and this change directory, nothing
      else — using `PREK_ALLOW_NO_CONFIG=1`, citing M600, D020, S099, S172 in the message
- [x] 4.3 Report to the director: the format, the two seams (no executable validator under this
      scope; `item` assumed from YF-1's concurrent change), and the M600 vocabulary write-back
      (`goal-falsified` added, seven kinds) for K

## 5. Reconcile with the shared fold (boundary correction, same session)

- [x] 5.1 Rename records to the fold's vocabulary: `rec` -> `event`, add `event_id`, and rename
      the events to `asked` / `nudged` / `noted` / `answered` / `timed_out` / `cancelled`
- [x] 5.2 Replace "first terminal record wins, later ones ignored" with the fold's actual
      contract: dedup on `event_id`, `(ts, event_id)` ordering, and an illegal transition failing
      the read loudly
- [x] 5.3 State the question declaration (initial, states, terminal, rules) in the spec and the
      README, so `questions/` is a declaration over the one fold rather than a second parser
- [x] 5.4 Run the four fixtures through `protocol/eventlog.py` from a scratch script; record the
      result in `design.md` — `answered / awaiting / timed_out / answered`, acceptance test passing
- [x] 5.5 Report the three seams the fold exposes: the answer-versus-sweeper race failing the
      read, cross-field validation of the pre-registered default being inexpressible in a
      declaration, and `deadline`/`on_timeout` being duplicated on the item's `awaiting` block
