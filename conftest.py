"""Root conftest — skip dispatch test modules that depend on removed APIs (Phase 3 rewrite)."""

collect_ignore = [
    "tests/test_dispatch.py",
    "tests/test_dispatch_auto_approve.py",
]
