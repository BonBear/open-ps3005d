import pytest

from ps3005d import protocol as p


def test_setpoint_formatting() -> None:
    assert p.set_voltage(5) == "VSET1:05.00"
    assert p.set_voltage(12.34) == "VSET1:12.34"
    assert p.set_current(1.5) == "ISET1:1.500"


@pytest.mark.parametrize("value", [-0.1, 30.01])
def test_voltage_out_of_range_rejected(value: float) -> None:
    with pytest.raises(ValueError):
        p.set_voltage(value)


def test_current_out_of_range_rejected() -> None:
    with pytest.raises(ValueError):
        p.set_current(5.001)


def test_memory_slots() -> None:
    assert p.save(1) == "SAV1"
    assert p.recall(5) == "RCL5"
    with pytest.raises(ValueError):
        p.recall(6)


def test_parse_float_ignores_trailing_junk() -> None:
    assert p.parse_float(b"12.00\x00") == 12.0
    assert p.parse_float(b"1.234K") == 1.234


def test_parse_status() -> None:
    s = p.parse_status(bytes([0x41]))
    assert s.mode is p.Mode.CV
    assert s.output_on
    assert not s.ocp_on
