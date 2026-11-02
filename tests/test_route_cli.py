"""Phase 2 CLI tests for `route recommend`, against committed sample_data
so they run fully offline."""

from pathlib import Path

from greenpilot.cli import main

SAMPLE = Path("sample_data")
WL = str(SAMPLE / "workloads.json")
GRID = str(SAMPLE / "grid_intensity_hourly.csv")


def _run(workload, duration, now, extra=None):
    args = [
        "route",
        "recommend",
        "--workloads",
        WL,
        "--grid",
        GRID,
        "--workload",
        workload,
        "--duration-hours",
        str(duration),
        "--now-hour",
        str(now),
    ]
    if extra:
        args += extra
    return main(args)


def test_deferrable_not_movable_is_time_shifted(capsys):
    rc = _run("nightly-etl", 6, 18)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Time-shifted" in out
    assert "lower carbon intensity" in out
    # Not movable -> region must stay eu-central-1 in both lines.
    assert "in eu-central-1" in out


def test_movable_job_can_relocate(capsys):
    rc = _run("model-training", 4, 18, ["--allowed-regions", "eu-north-1"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "relocated" in out
    assert "eu-north-1" in out


def test_non_deferrable_non_movable_is_declined(capsys):
    rc = _run("api-service", 2, 18)
    out = capsys.readouterr().out
    assert rc == 0
    assert "neither deferrable nor movable" in out
    # No reduction line should be printed.
    assert "% lower carbon intensity." not in out


def test_unknown_workload_errors():
    try:
        _run("nope", 4, 18)
        assert False, "expected SystemExit"
    except SystemExit as exc:
        assert "not found" in str(exc.code)


def test_bad_now_hour_errors():
    try:
        _run("nightly-etl", 4, 99)
        assert False, "expected SystemExit"
    except SystemExit as exc:
        assert "now-hour" in str(exc.code)
