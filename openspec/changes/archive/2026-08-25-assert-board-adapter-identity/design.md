## Context

S242: `GitHubIssuesAdapter` names `self.repo` on every call but never asserts who it is reading
as. Two `gh` identities on this machine see `BOARD_REPO` differently — one 404s, one reads fine.
The 404 is loud and already handled (`BoardError`). The feared failure is quiet: an identity with
*partial* visibility returning a shorter issue list with no error, which `ingest()` cannot tell
apart from "no commands right now."

## Decision — resolve + record, not configure + refuse

The adapter resolves its own authenticated login (`gh api user`'s `.login`) the first time it
performs a board read, caches it on the instance as `self.identity`, and includes it in every
`BoardError` it raises from that point on. It does not compare that login against an expected
value and does not refuse to run on a mismatch.

**Why not "take an expected login as configuration and refuse on mismatch" (the second candidate
in the dispatch).** It fails the stated CI constraint directly: in CI, `GH_TOKEN` is the only
credential, there is no second identity to distinguish from a first, and nothing in this repo
today knows what login a given `GH_TOKEN` maps to before making a call. A mismatch check needs
something to mismatch against; on a single-operator repo with an unattended CI credential, the
"expected" value would have to be hand-maintained configuration duplicating what `gh` already
knows, for a class of error (wrong account entirely) that already fails loudly via the existing
404. Building refusal machinery for a case that already fails safely, at the cost of a config
value that must work in an environment where it cannot be meaningfully validated, is the wrong
trade.

**Why not "assert at construction" (part of the third candidate).** `GitHubIssuesAdapter.__init__`
does no network I/O today (verified in `tests/board/test_github_create.py`: construction happens
before `_api` is monkeypatched, and no test call reaches `gh` before the first real method call).
Making construction itself perform a `gh api user` call would add a network round-trip to every
adapter instantiation, including ones a caller builds and never reads from, and would require
every existing fake-transport test to model a call it does not currently need to. Resolving lazily
on first read gets the same diagnosability — `self.identity` is set by the time any read-derived
`BoardError` fires or any successful read returns — without that cost.

**Where resolution lives:** `_issues()`, the one method every read-shaped call
(`open`/`list_events`/`_find_ref`) already funnels through. One `_ensure_identity()` call at its
top, memoized (`if self.identity is not None: return`), so the extra `gh api user` call happens at
most once per adapter instance, regardless of how many reads follow.

**Failure mode of resolution itself:** best-effort. If `gh api user` fails — no `gh` session at
all, distinct from "no access to this one repo" — `identity` stays `None` and the read that
triggered resolution proceeds on its own terms; a `BoardError` from a subsequent 404 just carries
no identity clause instead of a wrong one. Resolution must never become a new way for a working
`gh` session to fail a read it would otherwise have completed.

**Credential boundary, unchanged.** `gh api user` returns the caller's public profile (`login`,
`name`, `id`, …) — the same shape `gh auth status` already prints to a terminal without objection.
It is not the token. The class docstring's commitment — `gh` supplies auth, this class never
reads/prints/stores a credential — is not touched by adding a call that returns none.

## What this does and does not prove

**Proves:** after this change, any `BoardError` this adapter raises, and any code holding the
concrete `GitHubIssuesAdapter` (not the `BoardAdapter` Protocol — `inbox.py`/`loop.py`'s
`ingest()`/`project_all()` deliberately never gain a sixth method to call), can answer "who read
this" without a second manual `gh auth status`. The `boardlive` receipt (tasks §4) asserts this
against real GitHub: `adapter.identity` after a real read equals `BOARD_REPO`'s owner segment.

**Does not prove:** that a partial-visibility read is now detectable at the moment it happens.
Recording identity makes a *known-bad* identity's read diagnosable in hindsight; it does not add a
check that compares "issues returned" against "issues that should exist," because no source of
truth for the latter exists anywhere in this repository today. See the reachability finding below
for why this gap may be smaller than S242 feared.

## Finding: is partial visibility reachable for this call shape?

S242 stated this honestly as inferred from the code path, not observed, and asked that this change
determine it if possible. Reasoned from GitHub's documented permission model, not empirically
confirmed (no third `gh` identity with partial-but-not-full access to `BOARD_REPO` exists to test
against — only "full access" and "no access" were available):

`GET /repos/{owner}/{repo}/issues` — the endpoint `_issues()` calls — gates access **per
repository, not per issue**. For a private repo, an identity either has read access to the whole
repo (and receives the complete paginated list, filtered only by the `state` query parameter this
adapter itself sets to `all`) or it does not (404, GitHub's deliberate choice over 403 to avoid
confirming the repo exists). Standard GitHub issues have no per-issue visibility restriction
independent of repo-level access — that is a property of security advisories and some enterprise
features, not of `issues`. Fine-grained PAT scopes and org/team permissions are likewise
repo-level.

**Conclusion:** the specific "shorter list, no error" failure S242 named does not appear reachable
through this exact call shape. The two states this machine actually exhibited — full list, or
404 — are consistent with that model and are, as far as this reasoning goes, the only two states
possible for a single repo under this endpoint. This downgrades the quiet-neighbor risk from
"inferred and plausible" to "inferred and not supported by the documented permission model,"
without fully closing it — a future auth mechanism (e.g. a fine-grained PAT scoped to specific
issue *labels*, if GitHub ever ships one) could reopen it, and this change's identity-recording
mechanism is exactly what would make that reachable-again state diagnosable rather than silent.
This finding does not remove the value of resolving+recording identity: it is still what makes the
already-loud 404 case name *who* failed, and it is cheap insurance against a risk that is smaller
than first estimated rather than a risk this change concludes is zero.

## Consequence for the archived scheduled-workflow rejection

`fix-boardlive-reprojection-fixture-and-run-it`'s non-goals rejected a scheduled Actions workflow
for `test-boardlive` because it would need its own `gh` credential scoped to the `iorlas` identity
specifically — S242 wearing a different hat, per that change's own trail. This change does not
change that calculus: CI still has exactly one credential, and `self.identity` records what that
credential resolves to rather than asserting it must be a particular one. A scheduled workflow
remains rejected for the same reason; this change makes its failure mode (wrong identity, if one
were ever configured) diagnosable rather than silent, which is a smaller claim than "safe to
schedule now."

## Rejected alternative: attach identity to `Event`/ledger data

Considered stamping identity onto every `Event` `list_events()` returns, or having `inbox.py`
record it per poll in `ledger/board/consumed.jsonl`. Rejected: both routes require code outside
`GitHubIssuesAdapter` to call a sixth thing on the adapter, which the existing
`board-projection/inbox` requirement ("no method is called on the adapter object other than the
five named [Protocol methods]") already forbids for exactly this reason — a second adapter
(Forgejo, the requirement's own example) implementing only the five methods must keep working
without `ingest()`/`project_all()` gaining an adapter-specific dependency. Keeping identity
entirely inside the concrete `GitHubIssuesAdapter`, reachable only by code that already holds that
concrete type (this module's own error paths, and callers like `runtime/loop.py` that construct it
directly), respects that boundary.
