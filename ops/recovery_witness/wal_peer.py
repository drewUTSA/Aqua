"""Bridge one pinned physical replication slot to the independent station."""

import json
import os
import select
import struct
import sys
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from psycopg import pq

from wal_store import MAX_FRAME, WalIdentity, proof

SLOT = "aqua_station_wal_v1"
NAME = "aqua_station_wal_v1"


def lsn_number(value):
    upper, lower = value.decode("ascii").split("/")
    return int(upper, 16) * 2**32 + int(lower, 16)


def lsn_text(value):
    return f"{value >> 32:X}/{value & 0xFFFFFFFF:X}"


def station_confirm(station, profile, start, raw, input_stream, output):
    challenge = os.urandom(32)
    output.write(b"W" + struct.pack("!QI", start, len(raw)) + challenge + raw)
    output.flush()
    signed = input_stream.read(64)
    if len(signed) != 64:
        raise EOFError("independent_wal_station_closed")
    station.verify(signed, proof(profile, start, raw, challenge))


def run(connection, profile, offset, public_key, input_stream, output):
    if type(offset) is not int or offset < profile.first_lsn or offset >= 2**63:
        raise ValueError("wal_requested_position")
    station = Ed25519PublicKey.from_public_bytes(public_key)
    who = connection.exec_(b"IDENTIFY_SYSTEM")
    if (
        who.status != pq.ExecStatus.TUPLES_OK
        or who.ntuples != 1
        or (who.get_value(0, 0).decode("ascii"), int(who.get_value(0, 1)))
        != (profile.system_id, profile.timeline)
        or offset > lsn_number(who.get_value(0, 2))
    ):
        raise ValueError("wal_source_identity_or_timeline")
    command = f"START_REPLICATION SLOT {SLOT} PHYSICAL {lsn_text(offset)} TIMELINE {profile.timeline}"
    if connection.exec_(command.encode("ascii")).status != pq.ExecStatus.COPY_BOTH:
        raise ValueError("wal_slot_not_available")
    # A reconnect may only report an independently re-read position, before handling
    # any further WAL. Never recognize a position provided by the source as durable.
    station_confirm(station, profile, offset, b"", input_stream, output)

    def feedback():
        micros = time.time_ns() // 1000 - 946684800000000
        packet = struct.pack("!cQQQqB", b"r", offset, offset, 0, micros, 0)
        if connection.put_copy_data(packet) != 1 or connection.flush() != 0:
            raise RuntimeError("wal_source_feedback_unavailable")

    feedback()
    last = time.monotonic()
    while True:
        size, message = connection.get_copy_data(1)
        if size < 0:
            raise ValueError("wal_copy_stream_ended")
        if size == 0:
            ready = select.select([connection.socket, input_stream], [], [], 2)[0]
            if input_stream in ready:
                raise EOFError("wal_station_ended")
            if connection.socket in ready:
                connection.consume_input()
            if time.monotonic() - last >= 2:
                feedback()
                last = time.monotonic()
            continue
        data = bytes(message)
        if data[:1] == b"k" and len(data) == 18 and data[-1] in (0, 1):
            if data[-1]:
                feedback()
            continue
        if data[:1] != b"w" or not 25 < len(data) <= 25 + 16 * 1024 * 1024:
            raise ValueError("wal_source_frame")
        start = struct.unpack("!Q", data[1:9])[0]
        if start != offset:
            raise ValueError("wal_source_gap")
        for pos in range(25, len(data), MAX_FRAME):
            block = data[pos : pos + MAX_FRAME]
            station_confirm(station, profile, offset, block, input_stream, output)
            offset += len(block)
        feedback()
        last = time.monotonic()


def main():
    row = json.loads(sys.stdin.buffer.readline(8192))
    if set(row) != {"identity", "offset", "public_key", "socket", "password"} or row[
        "socket"
    ] not in ("/run/aqua-app-db", "127.0.0.1"):
        raise ValueError("wal_station_peer_configuration")
    from psycopg.conninfo import make_conninfo

    connect = make_conninfo(
        host=row["socket"],
        user="aqua_station_wal",
        password=row["password"],
        replication="true",
        application_name=NAME,
        connect_timeout=3,
        sslmode="disable",
    )
    conn = pq.PGconn.connect(connect.encode("ascii"))
    try:
        if conn.status != pq.ConnStatus.OK:
            raise RuntimeError("wal_replication_connection")
        run(
            conn,
            WalIdentity(**row["identity"]),
            row["offset"],
            bytes.fromhex(row["public_key"]),
            sys.stdin.buffer,
            sys.stdout.buffer,
        )
    finally:
        conn.finish()


if __name__ == "__main__":
    main()
