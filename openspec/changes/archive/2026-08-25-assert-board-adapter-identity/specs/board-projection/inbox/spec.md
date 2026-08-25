## ADDED Requirements

### Requirement: The GitHub adapter records which identity it is reading and writing as

`GitHubIssuesAdapter` SHALL resolve the authenticated `gh` login on the first board read it
performs, cache it for the lifetime of the instance, and make it available so a failed or
unexpectedly short read is diagnosable after the fact. Resolution SHALL be best-effort — a failure
to resolve the login SHALL NOT block or alter the outcome of the read that triggered it. Resolving
or recording identity SHALL NOT read, print, log, or store a credential; only the login name (the
same value `gh auth status` already prints) is used.

#### Scenario: Identity is resolved on first read and cached

- **WHEN** a `GitHubIssuesAdapter` performs its first board read (`open`, `list_events`, or
  internal ref lookup)
- **THEN** the authenticated `gh` login is resolved once and held on the instance
- **AND** a subsequent read on the same instance does not resolve it again

#### Scenario: A failed call names the identity that made it

- **WHEN** a `gh api` call this adapter makes fails after identity has been resolved
- **THEN** the raised `BoardError`'s message includes the resolved identity alongside the
  repository name

#### Scenario: Identity resolution failing does not block the read

- **WHEN** resolving the authenticated login itself fails (no `gh` session at all)
- **THEN** the read that triggered resolution proceeds and fails or succeeds on its own terms,
  unaffected by the resolution failure

#### Scenario: No credential is ever read, printed, logged, or stored

- **WHEN** identity is resolved or recorded, at any point
- **THEN** no token, header, or other credential value is read, printed, logged, or persisted by
  this mechanism — only the login name
