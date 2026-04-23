"""L1 tests for ``RunIntent`` — construction + field access.

``RunIntent`` is a pure dataclass; domain purity is preserved by
typing the ``StateManager`` reference as ``Any`` (see module docstring).
"""

from __future__ import annotations

import pytest

from a2sdlc.domain.models import GateConfig, StageName
from a2sdlc.domain.pipeline_event import PipelineEvent
from a2sdlc.domain.run_intent import RunIntent


@pytest.mark.unit
class TestRunIntent:
    def test_construction_and_field_access(self) -> None:
        event = PipelineEvent(key="ABC-1", trigger_stage=StageName.SPEC)
        intent = RunIntent(
            event=event,
            target_stage=StageName.SPEC,
            clean_body="body",
            user_prompt_override=None,
            gates=GateConfig(),
            self_answer=False,
            state_mgr=None,
            state=None,
            base="main",
            branch="feat/ABC-1",
        )
        assert intent.event is event
        assert intent.target_stage is StageName.SPEC
        assert intent.clean_body == "body"
        assert intent.user_prompt_override is None
        assert intent.base == "main"
        assert intent.branch == "feat/ABC-1"
