# Worked examples

Four question logs, each demonstrating scenarios from
`openspec/changes/define-question-frame-format/specs/question-frame/spec.md`. They are examples,
not real questions — nothing waits on them.

| File | Folds to | Demonstrates |
|---|---|---|
| `q-20260816T171204Z-3f9a2c1d.jsonl` | `answered` | a `cost-approval` question to `denis`; a `nudged` event that leaves the state alone; an answer arriving four days before the deadline |
| `q-20260816T171331Z-b7e40a52.jsonl` | `awaiting` | a request with `to: loop:shelf` — the same object as a question, differing only in who answers (D020) |
| `q-20260816T171402Z-5c1de9f7.jsonl` | `timed_out` | the deadline passing and the sweeper appending the answer that was pre-registered at ask time |
| `q-20260817T080200Z-9ab35e04.jsonl` | `answered` | a rejection that is a reply: `verdict: reject` with a `cause` and `next: retry` |

## The acceptance test

The dispatched criterion — *two branches suspend independently; answering one resumes exactly
that one and leaves the other suspended* — is the first two rows read together. Both were asked
within ninety seconds of each other by the same loop. The answer appended to `3f9a2c1d` names
that `qid` and nothing else; `b7e40a52` is untouched and still folds to `awaiting`.

Check it by hand, using the declaration this format supplies to the shared fold:

```python
import pathlib
from yosefactory.protocol.eventlog import Declaration, Rule, load

QUESTION = Declaration(
    initial="asked",
    states=frozenset({"awaiting", "answered", "timed_out", "cancelled"}),
    terminal=frozenset({"answered", "timed_out", "cancelled"}),
    rules={
        "asked": Rule(frozenset(), "awaiting",
                      required=(("item",), ("kind",), ("to",), ("text",), ("answer_type",),
                                ("return_to",), ("deadline",), ("on_timeout",)),
                      patterns={("on_timeout",): r"escalate|default:.+|abandon:.+"}),
        "nudged": Rule(frozenset({"awaiting"}), None, required=(("reason",),)),
        "noted": Rule(frozenset({"awaiting"}), None, required=(("body",),)),
        "answered": Rule(frozenset({"awaiting"}), "answered", required=(("verdict",), ("answer",))),
        "timed_out": Rule(frozenset({"awaiting"}), "timed_out", required=(("policy",), ("answer",))),
        "cancelled": Rule(frozenset({"awaiting"}), "cancelled", required=(("reason",),)),
    },
)

for path in sorted(pathlib.Path("questions/examples").glob("*.jsonl")):
    folded = load(path, QUESTION)
    print(folded.id, folded.state, folded.terminal)
```

Run against these fixtures it prints `answered`, `awaiting`, `timed_out`, `answered`. The
declaration is not committed anywhere yet — the fixtures were checked by running it from a
scratch script, and committing it alongside a test that runs under `make check` is sequenced
separately.

## Reading them

`(ts, event_id)` is the fold order — never file position — and every line repeats the `qid` so a
record pasted anywhere still names its question. Duplicates collapse on `event_id`; an illegal
transition fails the read rather than being skipped. Timeout records carry the `policy` they fired
under, so the reason a question closed itself is legible without consulting the `asked` record —
though the `asked` record is right there, unedited, on line one.
