#!/usr/bin/python3
"""Acquisition + TCP sender. Runs directly on the Red Pitaya board (needs the `rp` module)."""

import argparse
import atexit
import ctypes
import logging
import os
import queue
import signal
import socket
import sys
import threading
import time

import numpy as np
import rp  # vendor module, only importable on the Red Pitaya board itself

LOG_FORMAT = "%(asctime)s %(levelname)s [%(threadName)s] %(message)s"

TRIGGER_SOURCES = {
    "NOW": rp.RP_TRIG_SRC_NOW,
    "CHA_PE": rp.RP_TRIG_SRC_CHA_PE,
    "CHA_NE": rp.RP_TRIG_SRC_CHA_NE,
    "CHB_PE": rp.RP_TRIG_SRC_CHB_PE,
    "CHB_NE": rp.RP_TRIG_SRC_CHB_NE,
}

DECIMATIONS = {
    1: rp.RP_DEC_1,
    2: rp.RP_DEC_2,
    4: rp.RP_DEC_4,
    8: rp.RP_DEC_8,
    16: rp.RP_DEC_16,
    32: rp.RP_DEC_32,
    64: rp.RP_DEC_64,
    128: rp.RP_DEC_128,
    256: rp.RP_DEC_256,
    512: rp.RP_DEC_512,
    1024: rp.RP_DEC_1024,
    2048: rp.RP_DEC_2048,
    4096: rp.RP_DEC_4096,
    8192: rp.RP_DEC_8192,
    16384: rp.RP_DEC_16384,
    32768: rp.RP_DEC_32768,
    65536: rp.RP_DEC_65536,
}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pc-host", required=True, help="IP of the PC TCP receiver (pc_receiver.py)")
    parser.add_argument("--pc-port", type=int, default=5000, help="TCP port of the PC receiver")
    parser.add_argument("--samples", type=int, default=16384, help="Samples per acquisition packet (N)")
    parser.add_argument("--decimation", type=int, default=1024, choices=sorted(DECIMATIONS), help="RP acquisition decimation factor")
    parser.add_argument("--trigger-src", default="CHB_PE", choices=sorted(TRIGGER_SOURCES), help="RP acquisition trigger source")
    parser.add_argument("--channel", type=int, default=1, choices=(1, 2), help="RP input channel to acquire")
    parser.add_argument("--queue-size", type=int, default=50, help="Max packets buffered between acquisition and sender threads")
    parser.add_argument("--reconnect-delay", type=float, default=2.0, help="Seconds to wait before reconnecting to the PC after a network error")
    parser.add_argument("--pid-file", default="/tmp/rp_collector.pid", help="Where this process writes its own PID")
    return parser.parse_args()


def setup_logging():
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, stream=sys.stdout)


def write_pid_file(path):
    with open(path, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))


def remove_pid_file(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


class Acquirer:
    """Continuously acquires packets from the RP board into a shared queue."""

    def __init__(self, channel, samples, trigger_src, out_queue, stop_event):
        self.channel = rp.RP_CH_1 if channel == 1 else rp.RP_CH_2
        self.samples = samples
        self.trigger_src = trigger_src
        self.queue = out_queue
        self.stop_event = stop_event
        self.log = logging.getLogger("acquirer")

    def run(self):
        ibuff = rp.i16Buffer(self.samples)
        ptr = ctypes.cast(int(ibuff.cast()), ctypes.POINTER(ctypes.c_int16))

        while not self.stop_event.is_set():
            rp.rp_AcqStart()
            rp.rp_AcqSetTriggerSrc(self.trigger_src)

            while not self.stop_event.is_set() and not rp.rp_AcqGetBufferFillState()[1]:
                pass
            if self.stop_event.is_set():
                break

            rp.rp_AcqGetOldestDataRaw(self.channel, self.samples, ibuff.cast())
            data = np.ctypeslib.as_array(ptr, shape=(self.samples,)).copy()

            try:
                self.queue.put_nowait(data)
            except queue.Full:
                self.log.warning("Buffer full, dropping packet")

        self.log.info("Acquisition stopped")


class Sender:
    """Pulls packets from the shared queue and streams them to the PC receiver over TCP."""

    def __init__(self, host, port, in_queue, stop_event, reconnect_delay):
        self.host = host
        self.port = port
        self.queue = in_queue
        self.stop_event = stop_event
        self.reconnect_delay = reconnect_delay
        self.log = logging.getLogger("sender")

    def _connect(self):
        sock = None
        while not self.stop_event.is_set():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5.0)
                sock.connect((self.host, self.port))
                sock.settimeout(None)
                self.log.info("Connected to %s:%s", self.host, self.port)
                return sock
            except OSError as exc:
                self.log.warning("Connect to %s:%s failed (%s), retrying in %.1fs", self.host, self.port, exc, self.reconnect_delay)
                if sock is not None:
                    sock.close()
                time.sleep(self.reconnect_delay)
        return None

    def run(self):
        sock = self._connect()
        while sock is not None and not self.stop_event.is_set():
            try:
                packet = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                sock.sendall(packet.tobytes())
            except OSError as exc:
                self.log.error("Network error (%s), reconnecting", exc)
                sock.close()
                sock = self._connect()

        if sock is not None:
            sock.close()
        self.log.info("Sender stopped")


def main():
    args = parse_args()
    setup_logging()
    write_pid_file(args.pid_file)
    atexit.register(remove_pid_file, args.pid_file)
    log = logging.getLogger("main")

    stop_event = threading.Event()

    def handle_signal(signum, _frame):
        log.info("Signal %s received, shutting down", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    rp.rp_Init()
    rp.rp_AcqReset()
    rp.rp_AcqSetDecimation(DECIMATIONS[args.decimation])

    shared_queue = queue.Queue(maxsize=args.queue_size)
    acquirer = Acquirer(args.channel, args.samples, TRIGGER_SOURCES[args.trigger_src], shared_queue, stop_event)
    sender = Sender(args.pc_host, args.pc_port, shared_queue, stop_event, args.reconnect_delay)

    t_acq = threading.Thread(target=acquirer.run, name="Acquirer", daemon=True)
    t_send = threading.Thread(target=sender.run, name="Sender", daemon=True)
    t_acq.start()
    t_send.start()

    t_acq.join()
    t_send.join()

    rp.rp_Release()
    log.info("Collector stopped cleanly")


if __name__ == "__main__":
    main()
