"""Byte-level transports: real serial port and port discovery.

The device uses no line terminators: fixed-size replies are read by length, others
until the line goes quiet. All access is serialized behind one lock and paced,
because the firmware garbles or drops commands that arrive too fast. Measured on a
real unit (150 set/read-back cycles each): a single 50 ms gap still gave 1 bad
value, 40 ms gave 35; 75-100 ms after writes plus 30-40 ms after queries gave 0.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Protocol

import serial
from serial.tools import list_ports

from ps3005d.protocol import BAUDRATE

# Nuvoton USB CDC bridge used by Korad-family supplies (KA3005P, PS3005D, ...).
KNOWN_USB_IDS = {(0x0416, 0x5011)}


class Transport(Protocol):
    def write(self, cmd: str) -> None: ...

    def query(self, cmd: str, size: int | None = None) -> bytes:
        """Send ``cmd`` and return the reply: ``size`` bytes if given, else until quiet."""
        ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class PortInfo:
    device: str
    description: str
    vid: int | None
    pid: int | None

    @property
    def likely_ps3005d(self) -> bool:
        return (self.vid, self.pid) in KNOWN_USB_IDS


def list_serial_ports() -> list[PortInfo]:
    ports = [PortInfo(p.device, p.description or "", p.vid, p.pid) for p in list_ports.comports()]
    return sorted(ports, key=lambda p: (not p.likely_ps3005d, p.device))


class SerialTransport:
    def __init__(
        self,
        port: str,
        *,
        reply_timeout: float = 0.5,
        quiet_time: float = 0.02,
        write_gap: float = 0.10,
        query_gap: float = 0.04,
    ) -> None:
        self._ser = serial.Serial(
            port,
            baudrate=BAUDRATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=reply_timeout,
        )
        self._reply_timeout = reply_timeout
        self._quiet_time = quiet_time
        self._write_gap = write_gap
        self._query_gap = query_gap
        self._lock = threading.Lock()
        self._last = 0.0
        self._last_was_write = False

    def _pace(self) -> None:
        gap = self._write_gap if self._last_was_write else self._query_gap
        wait = self._last + gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)

    def _send(self, cmd: str) -> None:
        self._pace()
        self._ser.reset_input_buffer()
        self._ser.write(cmd.encode("ascii"))
        self._ser.flush()

    def write(self, cmd: str) -> None:
        with self._lock:
            self._send(cmd)
            self._last = time.monotonic()
            self._last_was_write = True

    def query(self, cmd: str, size: int | None = None) -> bytes:
        with self._lock:
            self._send(cmd)
            self._last_was_write = False
            if size is not None:
                data = bytearray(self._ser.read(size))
                self._last = time.monotonic()
                return bytes(data)
            # Unknown length: block for the first byte, then collect until the line is quiet.
            data = bytearray(self._ser.read(1))
            if data:
                self._ser.timeout = self._quiet_time
                try:
                    while chunk := self._ser.read(64):
                        data += chunk
                finally:
                    self._ser.timeout = self._reply_timeout
            self._last = time.monotonic()
            return bytes(data)

    def close(self) -> None:
        with self._lock:
            self._ser.close()  # pyserial: no-op if already closed
