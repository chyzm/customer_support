import sys

import pytest

from scripts import start


def test_container_entrypoint_migrates_then_execs_uvicorn(monkeypatch):
    events = []

    def fake_run(command, check):
        events.append(("run", command, check))

    def fake_execv(executable, command):
        events.append(("exec", executable, command))
        raise RuntimeError("exec intercepted")

    monkeypatch.setenv("PORT", "9123")
    monkeypatch.setattr(start.subprocess, "run", fake_run)
    monkeypatch.setattr(start.os, "execv", fake_execv)

    with pytest.raises(RuntimeError, match="exec intercepted"):
        start.main()

    assert events[0] == (
        "run",
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        True,
    )
    assert events[1] == (
        "exec",
        sys.executable,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "9123",
        ],
    )
