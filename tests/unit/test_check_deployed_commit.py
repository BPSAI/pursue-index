"""``scripts/check_deployed_commit.py``: the live site was built from this push."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_deployed_commit.py"
SHA = "b" * 40
OTHER = "c" * 40


def _load():
    spec = importlib.util.spec_from_file_location("check_deployed_commit", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load()


def wait(stamps, timeout=30):
    queue = list(stamps)
    now = [0.0]

    def fetch(url):
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    return mod.wait_for_commit(fetch, sha=SHA, timeout_secs=timeout, interval_secs=10,
                               sleep=lambda s: now.__setitem__(0, now[0] + s),
                               clock=lambda: now[0])


def test_match_passes():
    ok, msg = wait([{"commit": SHA}])
    assert ok, msg


def test_mismatch_fails_after_timeout():
    ok, msg = wait([{"commit": OTHER}])
    assert not ok and OTHER in msg and SHA in msg


def test_missing_field_fails():
    ok, msg = wait([{"schema": "x"}])
    assert not ok and "commit" in msg


def test_non_object_stamp_fails():
    ok, _ = wait([["not", "an", "object"]])
    assert not ok


def test_fetch_error_fails_after_timeout():
    ok, _ = wait([OSError("404")])
    assert not ok


def test_stale_then_fresh_passes():
    ok, msg = wait([{"commit": OTHER}, {"commit": SHA}])
    assert ok, msg


def test_stamp_url_has_cache_buster():
    assert mod.stamp_url("https://pursueindex.com/", 7).startswith("https://pursueindex.com/deploy-stamp.json?")


# --- edge blocks (a 403 from the CDN is not a wrong-commit result) ---------

import io  # noqa: E402
import re  # noqa: E402
import urllib.error  # noqa: E402

RUNBOOK = SCRIPT.parent / "runbook_verify_deploy.py"
WORKFLOW = SCRIPT.parents[1] / ".github" / "workflows" / "post-deploy-verify.yml"


def _http_error(code):
    return urllib.error.HTTPError("https://x/deploy-stamp.json", code, "Forbidden", {}, io.BytesIO(b""))


def test_a_403_at_the_deadline_reports_blocked_by_edge_not_wrong_commit():
    ok, msg = wait([_http_error(403)])
    assert not ok
    assert msg.startswith("blocked by edge")
    assert "not this commit" not in msg


def test_a_403_then_the_right_commit_passes():
    ok, msg = wait([_http_error(403), {"commit": SHA}])
    assert ok, msg


def test_a_wrong_commit_after_an_earlier_403_still_reports_the_commit():
    ok, msg = wait([_http_error(403), {"commit": OTHER}])
    assert not ok
    assert "not this commit" in msg and OTHER in msg


def test_main_exits_3_on_an_edge_block_and_writes_the_step_output(monkeypatch, tmp_path):
    out = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))

    def blocked(url):
        raise _http_error(403)

    monkeypatch.setattr(mod, "_fetch", blocked)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    rc = mod.main(["--sha", SHA, "--timeout-secs", "0"])
    assert rc == 3
    assert "edge_blocked=true" in out.read_text()


def test_the_fetch_sends_the_same_user_agent_as_the_passing_verify_steps(monkeypatch):
    runbook_ua = re.search(r'"User-Agent":\s*"([^"]+)"', RUNBOOK.read_text()).group(1)
    seen = {}

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

    def fake_urlopen(req, timeout):
        seen.update({k.lower(): v for k, v in req.header_items()})
        return _Resp(b'{"commit": "x"}')

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    mod._fetch("https://example.invalid/deploy-stamp.json")
    assert seen.get("user-agent") == runbook_ua
    assert "python-urllib" not in seen.get("user-agent", "").lower()


def test_the_issue_step_does_not_call_an_edge_block_a_broken_deploy():
    text = WORKFLOW.read_text()
    assert "id: stamp" in text
    assert "steps.stamp.outputs.edge_blocked" in text
    assert "deploy-verify-blocked" in text
