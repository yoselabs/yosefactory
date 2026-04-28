"""Gate-label provisioning helper for GitHub-backed consumers.

The four ``gate:*`` labels (matches ``domain/directives.py::_LABEL_GATE_RE``)
must exist on a repo before consumers can apply them via the Issues UI;
otherwise the label-form gate parser silently no-ops on a missing label.
``ensure_gate_labels`` is the one-time onboarding helper — exposed via
the ``a2sdlc ensure-gate-labels`` CLI. The dispatch hot path does not
call it (would add an API round-trip per run).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from github.Repository import Repository

logger = logging.getLogger(__name__)

GATE_LABELS: tuple[tuple[str, str, str], ...] = (
    ("gate:merge:human", "B60205", "Pause MERGE for human approval."),
    ("gate:merge:auto", "0E8A16", "Auto-merge after REVIEW approval."),
    ("gate:spec:human", "B60205", "Pause SPEC for human approval."),
    ("gate:spec:auto", "0E8A16", "Auto-advance past SPEC approval."),
)


def ensure_gate_labels(repo: Repository) -> list[str]:
    """Create any of the four ``gate:*`` labels that don't yet exist.

    Idempotent: lists current repo labels, creates only the missing
    ones. Returns the names that were created (empty list when the
    repo was already fully provisioned).
    """
    existing = {lbl.name for lbl in repo.get_labels()}
    created: list[str] = []
    for name, color, description in GATE_LABELS:
        if name in existing:
            continue
        repo.create_label(name=name, color=color, description=description)
        created.append(name)
        logger.info("ensure_gate_labels.created", extra={"label": name})
    return created
