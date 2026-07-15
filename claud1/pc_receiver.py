#!/usr/bin/env python3
"""TCP receiver for rp_collector.py. Runs on the PC, saves accumulated packets on shutdown."""

import argparse
import logging
import os
import signal
import socket
from datetime import datetime

import numpy as np

LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0", help="Interface to listen on")
    parser.add_argument("--port", type=int, default=5000, help="TCP port to listen on")
    parser.add_argument("--samples", type=int, default=16384, help="Samples per packet (N, must match rp_collector.py --samples)")
    parser.add_argument("--out-dir", default=".", help="Directory to write the .npz file into on shutdown")
    parser.add_argument("--recv-buffer", type=int, default=65536, help="Bytes requested per socket.recv() call")
    return parser.parse_args()


def setup_logging():
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)


def save(out_dir, all_data, log):
    if not all_data:
        log.info("No data collected, nothing to save")
        return
    name = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(out_dir, f"data_{name}.npz")
    np.savez_compressed(path, msts=np.array(all_data))
    log.info("Saved %d packets to %s", len(all_data), path)


def main():
    args = parse_args()
    setup_logging()
    log = logging.getLogger("receiver")

    packet_bytes = args.samples * 2  # int16
    all_data = []
    stop_requested = False

    def handle_signal(signum, _frame):
        nonlocal stop_requested
        log.info("Signal %s received, shutting down", signum)
        stop_requested = True

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(1.0)
    sock.bind((args.host, args.port))
    sock.listen(1)
    log.info("Listening on %s:%s (packet size=%d bytes)", args.host, args.port, packet_bytes)

    try:
        while not stop_requested:
            try:
                conn, addr = sock.accept()
            except socket.timeout:
                continue

            log.info("Connected: %s", addr)
            buffer = bytearray()
            with conn:
                conn.settimeout(1.0)
                while not stop_requested:
                    try:
                        data = conn.recv(args.recv_buffer)
                    except socket.timeout:
                        continue

                    if not data:
                        log.info("Peer closed connection")
                        break

                    buffer.extend(data)
                    while len(buffer) >= packet_bytes:
                        packet_bytes_chunk = buffer[:packet_bytes]
                        del buffer[:packet_bytes]
                        all_data.append(np.frombuffer(packet_bytes_chunk, dtype=np.int16))

                    log.debug("Received %d bytes (%d packets buffered)", len(data), len(all_data))
    finally:
        sock.close()
        save(args.out_dir, all_data, log)


if __name__ == "__main__":
    main()
