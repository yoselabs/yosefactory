# Tasks

- [x] 1. Measure what isolates, against the init event and against a canary turn, at the pinned version
- [x] 2. Separate the three leak surfaces and find the control for each
- [x] 3. Establish whether the emptied-home failure is auth-only or deeper
- [x] 4. Invert the home preflight: assert the credential store is reachable, not that the home is empty
- [x] 5. Make the isolated posture safe mode, strict tool servers, and commands disabled
- [x] 6. Refuse an isolated policy that names a tool server; move explicit re-admission to the opt-out
- [x] 7. Read `slash_commands`; widen `leaks` to what enters context; add `residue` for what does not
- [x] 8. Correct the false `cost_ceiling` capability claim
- [x] 9. Receipt: an isolated run in a hostile repository loads nothing, with an opted-out control
