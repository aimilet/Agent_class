from __future__ import annotations

from backend.core.runtime_review_settings import RuntimeReviewSettings, RuntimeReviewSettingsStore
from backend.core.settings import Settings


def test_runtime_review_settings_store_save_and_load(tmp_path):
    settings = Settings(runtime_root=str(tmp_path))
    settings.ensure_runtime_dirs()
    store = RuntimeReviewSettingsStore(settings)
    config = RuntimeReviewSettings(
        review_prep_max_answer_rounds=2,
        review_run_enable_validation_agent=False,
        review_run_default_parallelism=6,
    )

    store.save(config)
    loaded = store.load()

    assert loaded.review_prep_max_answer_rounds == 2
    assert loaded.review_run_enable_validation_agent is False
    assert loaded.review_run_default_parallelism == 6
