## MODIFIED Requirements

### Requirement: A closed set of question kinds, used only for routing

Every `asked` record SHALL carry `kind`, one of: `decision`, `ambiguity`, `out-of-depth`,
`gate-failed`, `cost-approval`, `skip-the-skill`, `elicitation`, `goal-falsified`.

`kind` SHALL be advisory — it routes and prioritises a question and MAY determine who is asked.
Nothing SHALL refuse, discard, or defer a question on the grounds that its kind is wrong for the
stage that emitted it, and no stage SHALL be required to declare in advance which kinds it may
emit. (S062: eleven hand-authored suspension clauses, zero fired, and the one real suspension
matched none of them — the vocabulary held, the per-stage prediction did not.)

A question MAY be emitted by the system rather than requested by a stage. `skip-the-skill` — the
offer to abandon a skill when frustration is detected (S090) — is the first such kind, and it
needs no separate machinery precisely because kind routes rather than gates: a question nothing
predicted is stored and answered like any other.

`elicitation` SHALL be marked blocking-by-design; the other seven SHALL be marked
blocking-by-failure. This property is derived from `kind` and SHALL NOT be set independently.

#### Scenario: An unexpected kind from a stage
- **WHEN** a stage emits a `goal-falsified` question and nothing predicted that it would
- **THEN** the question is stored and awaits an answer exactly as any other kind does

#### Scenario: A kind outside the closed set
- **WHEN** an `asked` record carries a `kind` not in the closed set
- **THEN** the record is invalid and the question is not considered well-formed

#### Scenario: A question nobody asked for
- **WHEN** the system itself emits a `skip-the-skill` question, with no stage having requested it
- **THEN** it is stored, routed, and answered exactly as a stage-requested question is
