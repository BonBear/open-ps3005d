"""Tests against a real PS3005D. Run with: PS3005D_PORT=/dev/ttyACM0 pytest -m hardware

Disconnect any load first: these tests switch the output on at low voltage/current.
"""

import os
import time
from collections.abc import Iterator

import pytest

from ps3005d.device import PowerSupply

pytestmark = pytest.mark.hardware


@pytest.fixture
def ps() -> Iterator[PowerSupply]:
    port = os.environ.get("PS3005D_PORT")
    if not port:
        pytest.skip("PS3005D_PORT not set")
    with PowerSupply.open(port) as dev:
        dev.output(False)
        v0, i0 = dev.voltage_setpoint(), dev.current_setpoint()
        try:
            yield dev
        finally:
            dev.output(False)
            dev.set_voltage(v0)
            dev.set_current(i0)


def test_identify(ps: PowerSupply) -> None:
    assert ps.identify()


def test_setpoint_roundtrip(ps: PowerSupply) -> None:
    ps.set_voltage(3.30)
    ps.set_current(0.100)
    assert ps.voltage_setpoint() == pytest.approx(3.30, abs=0.01)
    assert ps.current_setpoint() == pytest.approx(0.100, abs=0.001)


def test_output_toggle_and_status(ps: PowerSupply) -> None:
    ps.set_voltage(3.30)
    ps.set_current(0.100)
    ps.output(True)
    time.sleep(0.5)
    assert ps.status().output_on
    assert ps.measure().volts == pytest.approx(3.30, abs=0.1)
    ps.output(False)
    time.sleep(0.3)
    assert not ps.status().output_on


def test_memory_m5_save_and_recall(ps: PowerSupply) -> None:
    """Temporarily overwrites memory M5, then restores it."""
    ps.recall(5)
    time.sleep(0.3)
    original = (ps.voltage_setpoint(), ps.current_setpoint())
    try:
        _check_m5_roundtrip(ps)
    finally:
        ps.store_memory(5, *original)


def _check_m5_roundtrip(ps: PowerSupply) -> None:
    ps.store_memory(5, 4.44, 0.333)
    ps.set_voltage(1.00)
    ps.set_current(0.050)
    ps.output(True)
    time.sleep(0.3)
    ps.recall(5)
    time.sleep(0.3)
    assert ps.voltage_setpoint() == pytest.approx(4.44, abs=0.005)
    assert ps.current_setpoint() == pytest.approx(0.333, abs=0.0005)
    assert not ps.status().output_on  # recall switches the output off
