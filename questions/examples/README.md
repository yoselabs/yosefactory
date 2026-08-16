# Worked examples

Four question logs, each demonstrating scenarios from
`openspec/changes/define-question-frame-format/specs/question-frame/spec.md`. They are examples,
not real questions — nothing waits on them.

| File | Folds to | Demonstrates |
|---|---|---|
| `q-20260816T171204Z-3f9a2c1d.jsonl` | `answered` | a `cost-approval` question to `denis`; a `nudge` that leaves the state alone; an answer arriving four days before the deadline |
| `q-20260816T171331Z-b7e40a52.jsonl` | `awaiting` | a request with `to: loop:shelf` — the same object as a question, differing only in who answers (D020) |
| `q-20260816T171402Z-5c1de9f7.jsonl` | `timed_out` | the deadline passing and the sweeper appending the answer that was pre-registered at ask time |
| `q-20260817T080200Z-9ab35e04.jsonl` | `answered` | a rejection that is a reply: `verdict: reject` with a `cause` and `next: retry` |

## The acceptance test

The dispatched criterion — *two branches suspend independently; answering one resumes exactly
that one and leaves the other suspended* — is the first two rows read together. Both were asked
within ninety seconds of each other by the same loop. The answer appended to `3f9a2c1d` names
that `qid` and nothing else; `b7e40a52` is untouched and still folds to `awaiting`.

Check it by hand:

```sh
python3 - <<'PY'
import json, pathlib
TERMINAL = {"answer": "answered", "timeout": "timed_out", "cancel": "cancelled"}
for f in sorted(pathlib.Path("questions/examples").glob("*.jsonl")):
    recs = sorted((json.loads(l) for l in f.read_text().splitlines() if l.strip()),
                  key=lambda r: r["ts"])
    state = next((TERMINAL[r["rec"]] for r in recs if r["rec"] in TERMINAL), "awaiting")
    assert all(r["qid"] == f.stem for r in recs), f
    assert recs[0]["rec"] == "asked", f
    print(f"{f.stem}  {state}")
PY
```

## Reading them

`ts` order is the fold order, the first terminal record wins, and every line repeats the `qid` so
a record pasted anywhere still names its question. Timeout records carry the `policy` they fired
under, so the reason a question closed itself is legible without consulting the `asked` record —
though the `asked` record is right there, unedited, on line one.
