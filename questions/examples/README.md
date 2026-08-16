# Worked examples

Five question logs, each demonstrating scenarios from `openspec/specs/question-frame/spec.md`. They
are examples, not real questions — nothing waits on them.

| File | Folds to | Demonstrates |
|---|---|---|
| `q-20260816T171204Z-3f9a2c1d.jsonl` | `answered` | a `cost-approval` question to `denis`; a `nudged` event that leaves the state alone; an answer arriving four days before the deadline |
| `q-20260816T171331Z-b7e40a52.jsonl` | `awaiting` | a request with `to: loop:shelf` — the same object as a question, differing only in who answers (D020) |
| `q-20260816T171402Z-5c1de9f7.jsonl` | `timed_out` | the deadline passing and the sweeper appending the answer that was pre-registered at ask time |
| `q-20260817T080200Z-9ab35e04.jsonl` | `answered` | a rejection that is a reply: `verdict: reject` with a `cause` and `next: retry` |
| `q-20260818T164500Z-d41c8e37.jsonl` | `answered` | the race: Denis answers at 17:00:02, the sweeper appends `timed_out` at 17:00:03. The late record is absorbed, retained, and changes nothing |

## The acceptance test

The dispatched criterion — *two branches suspend independently; answering one resumes exactly
that one and leaves the other suspended* — is the first two rows read together. Both were asked
within ninety seconds of each other by the same loop. The answer appended to `3f9a2c1d` names
that `qid` and nothing else; `b7e40a52` is untouched and still folds to `awaiting`.

Check it by running the declaration, which is committed at
`src/yosefactory/protocol/question.py` and folded over every file here by
`tests/protocol/test_question_fold.py` under `make check`:

```python
import pathlib
from yosefactory.protocol import question

for path in sorted(pathlib.Path("questions/examples").glob("*.jsonl")):
    folded = question.load(path)
    print(folded.id, folded.state, folded.terminal)
```

It prints `answered`, `awaiting`, `timed_out`, `answered`, `answered`.

The declaration used to live here as a snippet instead, and it was wrong within a day of being
written: it scoped `noted` to `awaiting`, while the spec and the item declaration both make a note
legal from any state, closed included. A claim nobody executes is a claim nobody checks, which is why
it is code and a test now rather than a code block.

## The race, and why it is absorbed rather than tolerated

`q-20260818T164500Z-d41c8e37` is the fifth row and the reason `timed_out` carries **two** rules:

```
timed_out  from awaiting        -> timed_out, requiring policy and answer
           from any terminal    -> no state change, requiring nothing
```

Both writers were correct. The sweeper read the log before the answer landed and cannot fuse its read
and its append into one step, so it could not have avoided the race. That is the test the format
applies — **could the writer have avoided it?** — and it is why `answered` and `cancelled` get no such
rule: a deliberate writer has already read the log it is closing, so a second one is a defect and
fails the read.

The late record is kept and stays visible (`question.absorbed(folded)`), because a sweeper that is
simply wrong about deadlines looks identical to one that lost a fair race if the record is discarded.

## Reading them

`(ts, event_id)` is the fold order — never file position — and every line repeats the `qid` so a
record pasted anywhere still names its question. Duplicates collapse on `event_id`; an illegal
transition fails the read rather than being skipped. Timeout records carry the `policy` they fired
under, so the reason a question closed itself is legible without consulting the `asked` record —
though the `asked` record is right there, unedited, on line one.
