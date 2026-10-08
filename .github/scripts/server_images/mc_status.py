#!/usr/bin/env python3
"""Minecraft Server List Ping (status only), standard library only.

Usage: mc_status.py HOST PORT [--timeout SECONDS] [--protocol N]

Standalone on purpose: ci_check.py mounts this single file into a stock
Python container, so it must not import anything outside the standard library.

Sends handshake (next state 1) plus status request, reads the VarInt-framed
JSON response, prints it and exits 0. Exits 1 (message on stderr) on failure.
The default protocol -1 means "unknown/ping"; servers answer it with status.
"""

from __future__ import annotations

import argparse
import json
import socket
import struct
import sys

MAX_RESPONSE = 1 << 24  # 16 MiB sanity limit


class StatusError(Exception):
    pass


def encode_varint(value: int) -> bytes:
    """Encode a signed 32-bit integer as a Minecraft VarInt (-1 -> 5 bytes)."""
    if not -(1 << 31) <= value < (1 << 31):
        raise ValueError("VarInt out of range")
    value &= 0xFFFFFFFF
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def decode_varint(read_byte) -> int:
    """Decode a VarInt, pulling single bytes from ``read_byte() -> int``."""
    result = 0
    for shift in range(0, 35, 7):
        byte = read_byte()
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            if result >= 1 << 31:
                result -= 1 << 32
            return result
    raise StatusError("VarInt too long")


def encode_string(text: str) -> bytes:
    raw = text.encode("utf-8")
    return encode_varint(len(raw)) + raw


def frame(packet_id: int, payload: bytes = b"") -> bytes:
    body = encode_varint(packet_id) + payload
    return encode_varint(len(body)) + body


def build_handshake(host: str, port: int, protocol: int = -1) -> bytes:
    payload = encode_varint(protocol) + encode_string(host) + struct.pack(">H", port) + encode_varint(1)
    return frame(0x00, payload)


def build_status_request() -> bytes:
    return frame(0x00)


def _recv_exact(sock: socket.socket, count: int) -> bytes:
    chunks = []
    remaining = count
    while remaining:
        chunk = sock.recv(min(remaining, 65536))
        if not chunk:
            raise StatusError("connection closed before the full response was received")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_status_response(sock: socket.socket) -> str:
    def read_byte() -> int:
        return _recv_exact(sock, 1)[0]

    length = decode_varint(read_byte)
    if length <= 0 or length > MAX_RESPONSE:
        raise StatusError(f"invalid packet length {length}")
    data = _recv_exact(sock, length)
    pos = 0

    def next_byte() -> int:
        nonlocal pos
        if pos >= len(data):
            raise StatusError("truncated packet")
        pos += 1
        return data[pos - 1]

    packet_id = decode_varint(next_byte)
    if packet_id != 0x00:
        raise StatusError(f"unexpected packet id {packet_id:#x}")
    text_len = decode_varint(next_byte)
    text = data[pos : pos + text_len]
    if text_len < 0 or len(text) != text_len:
        raise StatusError("truncated status string")
    return text.decode("utf-8")


def query(host: str, port: int, timeout: float = 5.0, protocol: int = -1) -> str:
    """Return the raw status JSON text; raises StatusError/OSError on failure."""
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(build_handshake(host, port, protocol) + build_status_request())
        text = read_status_response(sock)
    try:
        parsed = json.loads(text)
    except ValueError as exc:
        raise StatusError(f"response is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise StatusError("response JSON is not an object")
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Minecraft server list ping")
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--protocol", type=int, default=-1)
    args = parser.parse_args(argv)
    try:
        text = query(args.host, args.port, args.timeout, args.protocol)
    except (StatusError, OSError, ValueError) as exc:
        print(f"status ping failed: {exc}", file=sys.stderr)
        return 1
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
