"""Tests for feedback routing — which stage handles feedback based on pipeline position."""

from a2sdlc.feedback_routing import resolve_target_stage
from a2sdlc.models import StageName


def test_no_stage_routes_to_spec():
    assert resolve_target_stage(current_stage=None) == StageName.SPEC


def test_spec_routes_to_spec():
    assert resolve_target_stage(current_stage=StageName.SPEC) == StageName.SPEC


def test_implement_routes_to_implement():
    assert (
        resolve_target_stage(current_stage=StageName.IMPLEMENT) == StageName.IMPLEMENT
    )


def test_review_routes_to_implement():
    assert resolve_target_stage(current_stage=StageName.REVIEW) == StageName.IMPLEMENT


def test_merge_routes_to_implement():
    assert resolve_target_stage(current_stage=StageName.MERGE) == StageName.IMPLEMENT
