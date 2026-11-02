"""Phase 1 CLI tests for the `telemetry` subcommands. Uses the committed
sample_data so these run fully offline, no AWS account."""

import csv
from pathlib import Path

from greenpilot.cli import main

SAMPLE = Path("sample_data")


def test_greenest_window_runs_and_reports(capsys):
    rc = main(
        [
            "telemetry",
            "greenest-window",
            "--workloads",
            str(SAMPLE / "workloads.json"),
            "--grid",
            str(SAMPLE / "grid_intensity_hourly.csv"),
            "--workload",
            "nightly-etl",
            "--duration-hours",
            "6",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "nightly-etl" in out
    assert "Greenest start" in out
    assert "Dirtiest start" in out


def test_greenest_window_unknown_workload_errors():
    try:
        main(
            [
                "telemetry",
                "greenest-window",
                "--workloads",
                str(SAMPLE / "workloads.json"),
                "--grid",
                str(SAMPLE / "grid_intensity_hourly.csv"),
                "--workload",
                "does-not-exist",
                "--duration-hours",
                "6",
            ]
        )
        assert False, "expected SystemExit for unknown workload"
    except SystemExit as exc:
        assert "not found" in str(exc.code)


def test_record_writes_one_row_per_workload_with_header(tmp_path):
    out = tmp_path / "telemetry.csv"
    rc = main(
        [
            "telemetry",
            "record",
            "--data-dir",
            str(SAMPLE),
            "--workloads",
            str(SAMPLE / "workloads.json"),
            "--grid",
            str(SAMPLE / "grid_intensity_hourly.csv"),
            "--window-start",
            "2026-01-01T18:00",
            "--window-end",
            "2026-01-02T00:00",
            "-o",
            str(out),
        ]
    )
    assert rc == 0
    rows = list(csv.DictReader(out.read_text(encoding="utf-8").splitlines()))
    assert len(rows) == 4  # one per workload in workloads.json
    assert {"workload_id", "co2e_kg", "g_co2e_per_kwh", "region"} <= set(rows[0])


def test_record_is_append_only(tmp_path):
    out = tmp_path / "telemetry.csv"
    common = [
        "telemetry",
        "record",
        "--data-dir",
        str(SAMPLE),
        "--workloads",
        str(SAMPLE / "workloads.json"),
        "--grid",
        str(SAMPLE / "grid_intensity_hourly.csv"),
        "-o",
        str(out),
    ]
    main(common + ["--window-start", "2026-01-01T18:00", "--window-end", "2026-01-02T00:00"])
    main(common + ["--window-start", "2026-01-01T00:00", "--window-end", "2026-01-01T06:00"])

    text = out.read_text(encoding="utf-8")
    # Exactly one header line, 8 data rows (4 workloads x 2 runs).
    assert text.count("workload_id,window_start") == 1
    rows = list(csv.DictReader(text.splitlines()))
    assert len(rows) == 8


def test_record_greener_window_has_lower_carbon(tmp_path):
    """The telemetry log must actually capture the intra-day swing: the same
    workload recorded in a clean window must show lower co2e than in a dirty
    one."""
    out = tmp_path / "telemetry.csv"
    common = [
        "telemetry",
        "record",
        "--data-dir",
        str(SAMPLE),
        "--workloads",
        str(SAMPLE / "workloads.json"),
        "--grid",
        str(SAMPLE / "grid_intensity_hourly.csv"),
        "-o",
        str(out),
    ]
    main(common + ["--window-start", "2026-01-01T18:00", "--window-end", "2026-01-02T00:00"])
    main(common + ["--window-start", "2026-01-01T00:00", "--window-end", "2026-01-01T06:00"])

    rows = list(csv.DictReader(out.read_text(encoding="utf-8").splitlines()))
    etl = [r for r in rows if r["workload_id"] == "nightly-etl"]
    assert len(etl) == 2
    evening, overnight = etl[0], etl[1]
    assert float(overnight["co2e_kg"]) < float(evening["co2e_kg"])


def test_record_rejects_backwards_window(tmp_path):
    out = tmp_path / "telemetry.csv"
    try:
        main(
            [
                "telemetry",
                "record",
                "--data-dir",
                str(SAMPLE),
                "--workloads",
                str(SAMPLE / "workloads.json"),
                "--grid",
                str(SAMPLE / "grid_intensity_hourly.csv"),
                "--window-start",
                "2026-01-02T00:00",
                "--window-end",
                "2026-01-01T00:00",
                "-o",
                str(out),
            ]
        )
        assert False, "expected SystemExit for backwards window"
    except SystemExit as exc:
        assert "window-end" in str(exc.code)
