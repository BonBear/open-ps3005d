from pathlib import Path

import pytest

from ps3005d.cli import main


def test_sim_status(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--sim", "status"]) == 0
    assert "SIMULATED" in capsys.readouterr().out


def test_sim_probe_prints_raw_replies(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--sim", "probe"]) == 0
    out = capsys.readouterr().out
    assert "STATUS?" in out and "hex=" in out


def test_out_of_range_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--sim", "set", "-v", "40"]) == 1
    assert "error" in capsys.readouterr().err


def test_sim_sequence(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    f = tmp_path / "s.csv"
    f.write_text("volts,amps,seconds\n5,1,0.5\n3,1,0.5\n")
    assert main(["--sim", "sequence", str(f), "--interval", "0.2"]) == 0
    out = capsys.readouterr().out
    assert "step   2" in out
