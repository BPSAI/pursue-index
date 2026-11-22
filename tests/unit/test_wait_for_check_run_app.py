"""``scripts/wait_for_check_run.py``: matching by app id and name."""

from __future__ import annotations

from tests.unit._wait_for_check_run_helpers import NAME, SCRIPT, cr, load, page, run

# ---- matching by app id and name -----------------------------------------

def test_same_name_run_from_another_app_is_ignored():
    ok, _, _ = run([page(cr("completed", "success", app_id=15368))], timeout=30)
    assert not ok and run.status == "fail"


def test_run_without_app_is_ignored():
    bare = {"id": 1, "name": NAME, "status": "completed", "conclusion": "success"}
    ok, _, _ = run([page(bare)], timeout=30)
    assert not ok


def test_app_id_default_is_single_constant_and_env_overridable(monkeypatch):
    assert SCRIPT.read_text().count("85455") == 1
    monkeypatch.setenv("WORKERS_BUILD_APP_ID", "7")
    assert load().default_app_id() == 7
