from __future__ import annotations

from datetime import UTC, datetime

import pytest

from packages.db.models import Episode, IllegalStageTransitionError
from packages.domain.enums import PipelineStage


def make_episode(**overrides: object) -> Episode:
    defaults: dict[str, object] = dict(subject_id=1, variation_profile_id=1)
    defaults.update(overrides)
    return Episode(**defaults)


# ---------------------------------------------------------------------------
# Illegal transitions
# ---------------------------------------------------------------------------


def test_cannot_skip_a_stage() -> None:
    episode = make_episode(stage=PipelineStage.CREATED)
    with pytest.raises(IllegalStageTransitionError):
        episode.advance_to(PipelineStage.FACTS_RECONCILED)


def test_cannot_move_backward() -> None:
    episode = make_episode(stage=PipelineStage.SCRIPTED)
    with pytest.raises(IllegalStageTransitionError):
        episode.advance_to(PipelineStage.RESEARCHING)


def test_cannot_cross_gate_a_without_approval() -> None:
    episode = make_episode(stage=PipelineStage.AWAITING_GATE_A, gate_a_approved_at=None)
    with pytest.raises(IllegalStageTransitionError):
        episode.advance_to(PipelineStage.SHOT_LIST)


def test_cannot_cross_gate_b_without_approval() -> None:
    episode = make_episode(stage=PipelineStage.AWAITING_GATE_B, gate_b_approved_at=None)
    with pytest.raises(IllegalStageTransitionError):
        episode.advance_to(PipelineStage.PUBLISHING)


def test_cannot_transition_out_of_published() -> None:
    episode = make_episode(stage=PipelineStage.PUBLISHED)
    with pytest.raises(IllegalStageTransitionError):
        episode.advance_to(PipelineStage.FAILED)


def test_cannot_retry_failed_into_wrong_stage() -> None:
    episode = make_episode(stage=PipelineStage.VOICE)
    episode.advance_to(PipelineStage.FAILED)
    assert episode.failed_at_stage == PipelineStage.VOICE.value
    with pytest.raises(IllegalStageTransitionError):
        episode.advance_to(PipelineStage.SUBTITLES)


# ---------------------------------------------------------------------------
# Legal transitions
# ---------------------------------------------------------------------------


def test_sequential_advance_is_legal() -> None:
    episode = make_episode(stage=PipelineStage.CREATED)
    episode.advance_to(PipelineStage.RESEARCHING)
    stage_after_first_advance = episode.stage
    assert stage_after_first_advance == PipelineStage.RESEARCHING
    episode.advance_to(PipelineStage.FACTS_RECONCILED)
    stage_after_second_advance = episode.stage
    assert stage_after_second_advance == PipelineStage.FACTS_RECONCILED


def test_gate_a_approval_allows_crossing() -> None:
    episode = make_episode(
        stage=PipelineStage.AWAITING_GATE_A,
        gate_a_approved_at=datetime.now(UTC),
    )
    episode.advance_to(PipelineStage.SHOT_LIST)
    assert episode.stage == PipelineStage.SHOT_LIST


def test_failed_recovery_into_the_failing_stage_is_legal() -> None:
    episode = make_episode(stage=PipelineStage.VOICE)
    episode.advance_to(PipelineStage.FAILED)
    episode.advance_to(PipelineStage.VOICE)
    assert episode.stage == PipelineStage.VOICE
    assert episode.failed_at_stage is None
