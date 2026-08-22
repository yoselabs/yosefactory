## ADDED Requirements

### Requirement: The loop's own CLI entrypoint surfaces the stall verdict in its exit code

`runtime/loop.py`'s `main()` (and, through it, `scheduled_main()` — the entrypoint the scheduler
template `ops/launchd/dev.yosefactory.loop.plist.template` already names) SHALL evaluate the stall
detector against the same ledger `run_loop` just wrote to, after `run_loop` returns and before the
process exits, and SHALL exit with the detector's own non-zero status (`STALLED` → 1, `STARVED` → 2)
rather than unconditionally returning 0. The detector's report line SHALL be printed regardless of
verdict, exactly as `stall.main()` already prints it standalone.

This is in addition to, not instead of, `stall.py` remaining invocable on its own — nothing about
this requirement narrows or replaces "the detector runs on a schedule, independent of any run."

**Reason, carried with the rule:** the detector was already correct and already invocable — S1021
found that nothing in this repository's own process ever *called* it. A `.github/workflows/*.yml`
that has never fired is its own catalogued failure mode (S195); wiring the exit code of an entrypoint
this repository already ships, and a scheduler template already names, costs one function call and
makes a freeze visible to whatever already invokes that entrypoint, without inventing new scheduling
infrastructure this repository has deliberately not built yet.

#### Scenario: A stalled ledger makes the CLI exit non-zero

- **WHEN** `main()` runs `run_loop` to completion and the resulting ledger's stall verdict is
  `STALLED`
- **THEN** the process exits with status 1
- **AND** the stall report line is printed to stdout before exit

#### Scenario: A starved ledger exits with its own distinct status

- **WHEN** the resulting ledger's stall verdict is `STARVED`
- **THEN** the process exits with status 2, distinguishable from `STALLED`'s status 1

#### Scenario: A healthy ledger exits zero exactly as before

- **WHEN** the resulting ledger's stall verdict is `OK`
- **THEN** the process exits 0, as `main()` already did before this requirement
