from pathlib import Path

import pytest

from ps3005d import sequence as seq
from ps3005d.sequence import Step

STEPS = [Step(5, 1, 2), Step(12, 0.5, 3)]


def test_position_and_boundaries() -> None:
    assert seq.position(STEPS, 1, 0) == (0, 0, 2)
    assert seq.position(STEPS, 1, 2.5) == (1, 0, 2.5)
    assert seq.position(STEPS, 1, 5) is None
    assert seq.position(STEPS, 2, 6) == (0, 1, 1)
    assert seq.position(STEPS, 0, 5 * 1000 + 1) == (0, 1000, 1)  # forever
    assert seq.next_boundary(STEPS, 1, 0.5) == 2
    assert seq.next_boundary(STEPS, 1, 4) == 5
    assert seq.next_boundary(STEPS, 1, 5) is None


def test_validate() -> None:
    seq.validate(STEPS)
    with pytest.raises(ValueError, match="no steps"):
        seq.validate([])
    with pytest.raises(ValueError, match="step 2"):
        seq.validate(STEPS, max_volts=10)
    with pytest.raises(ValueError, match="step 1"):
        seq.validate([Step(1, 6, 1)])
    with pytest.raises(ValueError, match="shorter"):
        seq.validate([Step(1, 1, 0.1)])


def test_csv_roundtrip(tmp_path: Path) -> None:
    f = tmp_path / "s.csv"
    seq.save(f, STEPS)
    assert f.read_text().splitlines()[0] == "volts,amps,seconds"
    assert seq.load(f) == STEPS


def test_vendor_table() -> None:
    # Format of the vendor app's 2.ini: step, volts, amps, seconds (tab separated).
    assert seq.loads("1\t5\t2\t1\n2\t10\t2\t1\n") == [Step(5, 2, 1), Step(10, 2, 1)]
    with pytest.raises(ValueError, match="line 1"):
        seq.loads("1 2 3\n")
