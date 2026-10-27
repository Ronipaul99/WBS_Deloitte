import socket
import struct
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from re import fullmatch, sub
from typing import BinaryIO, Protocol

from starlette.concurrency import run_in_threadpool

from app.core.config import Settings

CLAMAV_COMMAND_INSTREAM = b"zINSTREAM\0"
CLAMAV_COMMAND_PING = b"zPING\0"
CLAMAV_STREAM_TERMINATOR = struct.pack("!I", 0)
CLAMAV_STREAM_CHUNK_BYTES = 1024 * 1024


class MalwareScanStatus(StrEnum):
    CLEAN = "clean"
    INFECTED = "infected"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class MalwareScanResult:
    status: MalwareScanStatus
    detection_identifier: str | None = None


class MalwareScanner(Protocol):
    async def scan(self, path: Path) -> MalwareScanResult: ...

    async def check(self) -> None: ...


class ScannerUnavailableError(RuntimeError):
    pass


class ScannerInputReadError(RuntimeError):
    pass


class _ClamAVProtocolError(RuntimeError):
    pass


def _remaining_timeout(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("scanner deadline exceeded")
    return remaining


def _receive_response(connection: socket.socket, maximum_bytes: int, deadline: float) -> bytes:
    response = bytearray()
    while True:
        connection.settimeout(_remaining_timeout(deadline))
        chunk = connection.recv(min(4096, maximum_bytes + 1 - len(response)))
        if not chunk:
            raise _ClamAVProtocolError("truncated scanner response")
        response.extend(chunk)
        if len(response) > maximum_bytes:
            raise _ClamAVProtocolError("oversized scanner response")
        terminator = response.find(b"\0")
        if terminator >= 0:
            if terminator != len(response) - 1:
                raise _ClamAVProtocolError("invalid scanner response framing")
            return bytes(response[:terminator])


def _sanitize_detection_identifier(value: str) -> str:
    safe_value = sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_.-")[:80]
    return safe_value or "detected"


def _parse_scan_response(response: bytes) -> MalwareScanResult:
    try:
        decoded = response.decode("ascii")
    except UnicodeDecodeError:
        return MalwareScanResult(MalwareScanStatus.UNAVAILABLE)
    if decoded == "stream: OK":
        return MalwareScanResult(MalwareScanStatus.CLEAN)
    match = fullmatch(r"stream: (.{1,200}) FOUND", decoded)
    if match:
        return MalwareScanResult(
            MalwareScanStatus.INFECTED,
            _sanitize_detection_identifier(match.group(1)),
        )
    return MalwareScanResult(MalwareScanStatus.UNAVAILABLE)


class ClamAVScanner:
    def __init__(self, settings: Settings) -> None:
        if not settings.clamav_host:
            raise ValueError("ClamAV configuration is incomplete.")
        self.host = settings.clamav_host
        self.port = settings.clamav_port
        self.connect_timeout = settings.clamav_connect_timeout_seconds
        self.scan_timeout = settings.clamav_scan_timeout_seconds
        self.response_max_bytes = settings.clamav_response_max_bytes
        self.maximum_bytes = settings.max_upload_bytes

    async def scan(self, path: Path) -> MalwareScanResult:
        return await run_in_threadpool(self._scan_sync, path)

    async def check(self) -> None:
        await run_in_threadpool(self._check_sync)

    def _connect(self) -> socket.socket:
        return socket.create_connection(
            (self.host, self.port),
            timeout=self.connect_timeout,
        )

    def _scan_sync(self, path: Path) -> MalwareScanResult:
        try:
            size_bytes = path.stat().st_size
            if size_bytes < 1 or size_bytes > self.maximum_bytes or path.is_symlink():
                raise ScannerInputReadError("scanner input is unavailable")
            source = path.open("rb")
        except ScannerInputReadError:
            raise
        except OSError:
            raise ScannerInputReadError("scanner input is unavailable") from None

        deadline = time.monotonic() + self.scan_timeout
        with source:
            try:
                with self._connect() as connection:
                    connection.settimeout(_remaining_timeout(deadline))
                    connection.sendall(CLAMAV_COMMAND_INSTREAM)
                    self._send_file(connection, source, deadline)
                    connection.settimeout(_remaining_timeout(deadline))
                    connection.sendall(CLAMAV_STREAM_TERMINATOR)
                    response = _receive_response(
                        connection,
                        self.response_max_bytes,
                        deadline,
                    )
            except ScannerInputReadError:
                raise
            except (OSError, TimeoutError, _ClamAVProtocolError):
                return MalwareScanResult(MalwareScanStatus.UNAVAILABLE)
        return _parse_scan_response(response)

    def _send_file(
        self,
        connection: socket.socket,
        source: BinaryIO,
        deadline: float,
    ) -> None:
        byte_count = 0
        while True:
            try:
                chunk = source.read(CLAMAV_STREAM_CHUNK_BYTES)
            except OSError:
                raise ScannerInputReadError("scanner input is unavailable") from None
            if not chunk:
                return
            byte_count += len(chunk)
            if byte_count > self.maximum_bytes:
                raise ScannerInputReadError("scanner input is unavailable")
            connection.settimeout(_remaining_timeout(deadline))
            connection.sendall(struct.pack("!I", len(chunk)) + chunk)

    def _check_sync(self) -> None:
        deadline = time.monotonic() + self.connect_timeout
        try:
            with self._connect() as connection:
                connection.settimeout(_remaining_timeout(deadline))
                connection.sendall(CLAMAV_COMMAND_PING)
                response = _receive_response(connection, 64, deadline)
                if response != b"PONG":
                    raise _ClamAVProtocolError("invalid scanner readiness response")
        except (OSError, TimeoutError, _ClamAVProtocolError):
            raise ScannerUnavailableError("Malware scanner is unavailable.") from None
