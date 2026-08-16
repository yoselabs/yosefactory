## ADDED Requirements

### Requirement: Why a turn failed is a second axis, not a wider outcome

Every turn record MAY carry a `failure_kind` field naming why the turn failed. It SHALL be absent
or null unless `outcome` is `failed`, and a record carrying a `failure_kind` alongside any other
outcome SHALL be rejected at write time.

**Two axes, one record.** `outcome` answers *did the turn advance* and is exactly four values,
frozen, because every row ever written is compared against every other row. `failure_kind` answers
*why did it fail*, and is **executor-facing and expected to change** as vendors and harnesses
change. Widening `outcome` to carry the reason would conflate the two questions and break the
four-value contract that governing decisions are typed against.

`failure_kind` SHALL be drawn from a closed set, and that set is the union of the executor's two
failing vocabularies flattened onto the single question *why*:

| `failure_kind` | Source |
|---|---|
| `budget_exhausted` | the executor stopped for want of budget |
| `turn_limit` | the executor hit its turn ceiling |
| `cancelled` | the run was cancelled |
| `auth` | the model refused the credentials |
| `rate_limit` | the model was reachable but the quota was not available |
| `crash` | the executor died |
| `bad_output` | the executor produced output the reader could not use |
| `task_error` | the work itself errored |
| `version_mismatch` | the executor and the harness disagreed on version |

The two vocabularies are disjoint in their names, so the flattening is unambiguous and a reader
never has to know which level a value came from.

`failure_kind` MAY be null even when `outcome` is `failed`: a supervisor authoring a record for a
process it killed has no executor reason to report, and `enforced_by: harness` already says who
ended the run. A null `failure_kind` SHALL NOT be read as "no reason exists" — only as "the writer
had no typed reason to give".

**Reason, carried with the rule:** `rate_limit` SHALL be distinguishable from every other failure
and SHALL NOT be folded into a generic failure ([[architecture.md]] §7b rule 3). The model draws
from the same rolling window as the operator's own interactive use, so a factory **starved** of
quota and a factory whose model is **broken** are different conditions demanding different
responses — one waits, the other is fixed. Free text in `note` cannot be queried, so a stall
detector reading only `outcome` and `note` cannot tell them apart.

#### Scenario: A starved run is distinguishable from a broken one

- **WHEN** one run fails because the quota window is exhausted and another fails because the
  executor crashed
- **THEN** both records carry `outcome: failed`
- **AND** the first carries `failure_kind: rate_limit` and the second `failure_kind: crash`
- **AND** a consumer separates them without reading free text

#### Scenario: A failure kind on a non-failed outcome is rejected

- **WHEN** a record is written with `outcome: advanced` and a `failure_kind`
- **THEN** the write is rejected with an error naming both fields
- **AND** no record is appended to the stream

#### Scenario: A kind outside the closed set is rejected

- **WHEN** a record is written with a `failure_kind` outside the closed set
- **THEN** the write is rejected with an error naming the offending value and the valid ones

#### Scenario: A harness kill needs no failure kind

- **WHEN** the supervisor authors a record for a process it terminated
- **THEN** the record carries `outcome: failed` and `enforced_by: harness`
- **AND** a null or absent `failure_kind` is well-formed

#### Scenario: A record written before the field is still readable

- **WHEN** a record with no `failure_kind` key is read
- **THEN** it is rebuilt with `failure_kind` null and no error
