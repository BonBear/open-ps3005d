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
