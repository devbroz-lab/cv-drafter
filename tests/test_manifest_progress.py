"""
Tests for the per-step timing + progress helpers and append_warning idempotency
in pipeline/manifest.py (used by GET /sessions/{id}/manifest).
"""

from pipeline.manifest import (
    STEP_ORDER,
    append_warning,
    compute_progress,
    create_manifest,
    current_running_step,
    load_manifest,
    update_step,
)


class TestComputeProgress:
    def test_empty_is_zero(self):
        assert compute_progress([]) == 0

    def test_all_done_is_100(self):
        steps = [{"name": s, "status": "done"} for s in STEP_ORDER]
        assert compute_progress(steps) == 100

    def test_single_running_half_step(self):
        steps = [{"name": "cv_extractor", "status": "running"}]
        # 0.5 / len(STEP_ORDER) * 100
        assert compute_progress(steps) == round(0.5 / len(STEP_ORDER) * 100)

    def test_partial_mix(self):
        steps = [
            {"name": "cv_extractor", "status": "done"},
            {"name": "tor_summarizer", "status": "done"},
            {"name": "checkpoint_1", "status": "pending"},
        ]
        # 1 + 1 + 0.5 = 2.5 of 10 → 25
        assert compute_progress(steps) == 25

    def test_waiting_and_failed_count_zero(self):
        steps = [
            {"name": "cv_extractor", "status": "failed"},
            {"name": "tor_summarizer", "status": "waiting"},
        ]
        assert compute_progress(steps) == 0


class TestCurrentRunningStep:
    def test_running_step_wins(self):
        steps = [
            {"name": "cv_extractor", "status": "done"},
            {"name": "tor_summarizer", "status": "running"},
            {"name": "checkpoint_1", "status": "pending"},
        ]
        assert current_running_step(steps) == "tor_summarizer"

    def test_checkpoint_pending_fallback(self):
        steps = [
            {"name": "cv_extractor", "status": "done"},
            {"name": "tor_summarizer", "status": "done"},
            {"name": "checkpoint_1", "status": "pending"},
        ]
        assert current_running_step(steps) == "checkpoint_1"

    def test_none_when_idle(self):
        steps = [{"name": "cv_extractor", "status": "done"}]
        assert current_running_step(steps) is None


class TestUpdateStepTiming:
    def test_started_at_stamped_on_running_and_preserved(self, tmp_path):
        create_manifest(tmp_path, run_id="t", cv_path="", tor_path="", params={})
        update_step(tmp_path, "cv_extractor", "running")
        m1 = load_manifest(tmp_path)
        step1 = next(s for s in m1["steps"] if s["name"] == "cv_extractor")
        assert step1["status"] == "running"
        assert step1["started_at"] is not None
        assert step1["completed_at"] is None
        started = step1["started_at"]

        update_step(tmp_path, "cv_extractor", "done")
        m2 = load_manifest(tmp_path)
        step2 = next(s for s in m2["steps"] if s["name"] == "cv_extractor")
        assert step2["status"] == "done"
        assert step2["started_at"] == started  # preserved, not overwritten
        assert step2["completed_at"] is not None

    def test_new_manifest_steps_have_started_at_field(self, tmp_path):
        create_manifest(tmp_path, run_id="t", cv_path="", tor_path="", params={})
        m = load_manifest(tmp_path)
        assert all("started_at" in s for s in m["steps"])


class TestAppendWarningIdempotency:
    def test_identical_warning_appended_once(self, tmp_path):
        create_manifest(tmp_path, run_id="t", cv_path="", tor_path="", params={})
        for _ in range(3):
            append_warning(tmp_path, stage="cv_extractor", kind="extraction_warning", message="dup")
        warnings = load_manifest(tmp_path).get("warnings", [])
        assert len(warnings) == 1

    def test_different_messages_both_kept(self, tmp_path):
        create_manifest(tmp_path, run_id="t", cv_path="", tor_path="", params={})
        append_warning(tmp_path, stage="cv_extractor", kind="extraction_warning", message="a")
        append_warning(tmp_path, stage="cv_extractor", kind="extraction_warning", message="b")
        assert len(load_manifest(tmp_path).get("warnings", [])) == 2
