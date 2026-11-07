"""One actual original-case continuation; no model/precondition replay."""
from current_staging_fence_recovery_support import resume_owned_staging_fence


def test_resume_recorded_staging_fence_original_obligation():
    resume_owned_staging_fence()
