## ADDED Requirements

### Requirement: The live receipt against real GitHub is runnable on demand, outside `make check`

This capability's own `boardlive`-marked tests (`tests/board/test_reprojection.py`) SHALL be
runnable via a dedicated `make` target that is not part of `make check`'s default selection. The
target SHALL exist for the same reason `make test-live` does — the tests it runs mutate external
state and need `gh` auth, so joining `make check` would make every default build depend on network
access and credentials the marker itself declares it needs.

A change that touches `src/yosefactory/board/` SHALL run this target before merge — this is a
documented step, not a mechanically enforced gate, and the exclusion from `make check` stays in
place regardless (S243: excluding a check from the default suite is correct; never running it at
all is the defect this requirement closes).

#### Scenario: The marker is runnable without joining the default suite

- **WHEN** a developer runs `make test-boardlive`
- **THEN** it invokes `pytest -m boardlive` against `tests/board/`
- **AND** `make check` (and therefore `make test`) still excludes `boardlive` from its own run

#### Scenario: A board-touching change carries a live-receipt result

- **WHEN** a change modifies anything under `src/yosefactory/board/`
- **THEN** the change's own verification record names the verbatim result of `make test-boardlive`
  (or `pytest -q -m boardlive tests/board/`) run against `BOARD_REPO`, not only `make check`
