"""How to run a unit of work, kept out of the frame that says what the work is.

D019's frame is the unit of falsification: `goal`, `method` and `assumptions` are claims that can be
**wrong**, and they live in the item's permanent trail and in every comparison of one run's frame to
another's. A skill name and an output path cannot be wrong, only stale, and they are disposable.

So the frame is not the channel for them. Three things, three parameters:

    frame       what the work is    epistemic, falsifiable, permanent
    invocation  how to run it       plumbing, disposable, never in the trail
    limits      what bounds it
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Invocation:
    """The plumbing one run needs: which skill to follow, what vocabulary it may report in, and
    where to write its answer."""

    skill: Path | None = None
    vocabulary: Path | None = None
    proposal_path: Path | None = None

    def render(self) -> str:
        lines = []
        if self.skill is not None:
            lines.append(f"Follow the skill at {self.skill}.")
        if self.vocabulary is not None:
            lines.append(
                f"The vocabulary at {self.vocabulary} names the required fields for whichever "
                "event you write -- check it before you do."
            )
        if self.proposal_path is not None:
            lines.append(f"Write your one event to {self.proposal_path}.")
        return "\n".join(lines)
