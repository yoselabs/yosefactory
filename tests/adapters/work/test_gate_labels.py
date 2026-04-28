"""Tests for ``adapters.work.gate_labels.ensure_gate_labels``."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from a2sdlc.adapters.work.gate_labels import GATE_LABELS, ensure_gate_labels


@pytest.mark.unit
class TestEnsureGateLabels:
    def test_creates_all_four_when_repo_empty(self) -> None:
        mock_repo = MagicMock()
        mock_repo.get_labels.return_value = []

        created = ensure_gate_labels(mock_repo)

        assert created == [name for name, _, _ in GATE_LABELS]
        assert mock_repo.create_label.call_count == 4

    def test_skips_existing_labels(self) -> None:
        existing = MagicMock()
        existing.name = "gate:merge:human"
        other = MagicMock()
        other.name = "bug"
        mock_repo = MagicMock()
        mock_repo.get_labels.return_value = [existing, other]

        created = ensure_gate_labels(mock_repo)

        assert "gate:merge:human" not in created
        assert created == ["gate:merge:auto", "gate:spec:human", "gate:spec:auto"]
        assert mock_repo.create_label.call_count == 3

    def test_idempotent_on_fully_provisioned_repo(self) -> None:
        labels = []
        for name, _, _ in GATE_LABELS:
            lbl = MagicMock()
            lbl.name = name
            labels.append(lbl)
        mock_repo = MagicMock()
        mock_repo.get_labels.return_value = labels

        created = ensure_gate_labels(mock_repo)

        assert created == []
        mock_repo.create_label.assert_not_called()
