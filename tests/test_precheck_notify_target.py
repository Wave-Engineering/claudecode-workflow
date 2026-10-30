"""scripts/precheck-notify-target.sh: /precheck's notice goes to BJ or to a named lead (#1365)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "precheck-notify-target.sh"


def _run(repo: Path, self_name: str = "sorting-hat") -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(SCRIPT), str(repo), self_name], capture_output=True, text=True, timeout=30)


def _identity(tmp: Path, data) -> Path:
    (tmp / ".claude").mkdir(exist_ok=True)
    text = data if isinstance(data, str) else json.dumps(data)
    (tmp / ".claude" / "agent-identity.json").write_text(text)
    return tmp


BASE = {"dev_team": "oaw", "dev_name": "sorting-hat", "dev_avatar": "🎩"}


def test_notify_target_no_file_is_bj(tmp_path):
    r = _run(tmp_path)
    assert (r.returncode, r.stdout) == (0, "bj\n")


def test_notify_target_no_lead_falls_back_to_bj(tmp_path):
    """babelfish's ruling on #1365: an identity with no `lead` routes to BJ."""
    r = _run(_identity(tmp_path, BASE))
    assert (r.returncode, r.stdout, r.stderr) == (0, "bj\n", "")


def test_notify_target_lead_naming_another(tmp_path):
    r = _run(_identity(tmp_path, {**BASE, "lead": {"session": "babelfish", "dev_name": "babelfish"}}))
    assert (r.returncode, r.stdout) == (0, "lead babelfish babelfish\n")


def test_notify_target_session_and_dev_name_differ(tmp_path):
    r = _run(_identity(tmp_path, {**BASE, "lead": {"session": "cc-lead-1", "dev_name": "babelfish"}}))
    assert r.stdout == "lead cc-lead-1 babelfish\n"


def test_notify_target_self_is_the_lead_is_bj(tmp_path):
    """A lead running its own precheck in a grunt's worktree notifies BJ, not itself."""
    r = _run(_identity(tmp_path, {**BASE, "lead": {"session": "babelfish", "dev_name": "babelfish"}}), "babelfish")
    assert (r.returncode, r.stdout) == (0, "bj\n")


@pytest.mark.parametrize("data,why", [
    ({**BASE, "lead": "babelfish"}, "not an object"),
    ({**BASE, "lead": {"dev_name": "babelfish"}}, "lead.session"),
    ({**BASE, "lead": {"session": "babelfish"}}, "lead.dev_name"),
    ({**BASE, "lead": {"session": "bad name", "dev_name": "babelfish"}}, "lead.session"),
    ({**BASE, "lead": {"session": "babelfish", "dev_name": "$(x)"}}, "lead.dev_name"),
    ({**BASE, "lead": {"session": 7, "dev_name": "babelfish"}}, "lead.session"),
    ("{not json", "not valid JSON"),
    ("[1]", "not a JSON object"),
], ids=["string", "no-session", "no-dev-name", "space", "metachar", "number", "not-json", "array"])
def test_notify_target_malformed_lead_is_bj_exit_3(tmp_path, data, why):
    r = _run(_identity(tmp_path, data))
    assert (r.returncode, r.stdout) == (3, "bj\n")
    assert why in r.stderr


def test_notify_target_usage_is_exit_2(tmp_path):
    r = subprocess.run(["bash", str(SCRIPT), str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 2
