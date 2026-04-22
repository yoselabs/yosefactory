# Document Templates

Skeletons for each step of the design process (see [`../vision/03-design-process.md`](../vision/03-design-process.md)).

| Template | Used for | Goes in |
|---|---|---|
| [`brief.md`](brief.md) | Step (0) — Product brief | `docs/briefs/YYYY-MM-DD-<slug>.md` |
| [`pitch.md`](pitch.md) | Step (1) — Shape Up pitch | `docs/pitches/YYYY-MM-DD-<slug>.md` |
| [`rfc.md`](rfc.md) | Step (2) — Design doc / RFC | `docs/rfcs/NNNN-<slug>.md` |
| [`adr.md`](adr.md) | Step (3) — Architecture Decision Record | `docs/adr/NNNN-<slug>.md` |
| [`spec.md`](spec.md) | Step (4) — Implementation spec | `docs/superpowers/specs/YYYY-MM-DD-<slug>-design.md` |
| [`eval-plan.md`](eval-plan.md) | Step (5) — Eval plan | `docs/evals/YYYY-MM-DD-<slug>.md` |
| [`runbook.md`](runbook.md) | Step (6) — Operational runbook | `docs/runbooks/<component>.md` |
| [`retro.md`](retro.md) | Step (8) — Retro / Postmortem | `docs/retros/YYYY-MM-DD-<slug>.md` |
| [`changelog.md`](changelog.md) | Step (7) — Changelog (one per repo) | `CHANGELOG.md` at repo root |

All templates share YAML frontmatter so agents can parse them consistently.

## Link conventions in frontmatter

- `null` — not applicable (e.g. a standalone ADR not derived from an RFC).
- `""` (empty string) — required link is not yet filled in; the linter flags this as incomplete.
- A path — filled in. Relative paths only, resolved from the document's location.

CI link-checker treats `null` and a valid resolvable path as green; empty string and dangling path as red.
