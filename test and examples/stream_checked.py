#!/usr/bin/python3
"""Acquisition for the existing GUI; checked API calls and calibrated ADC codes.

The TCP packet format stays int16: CH1 followed by CH2 when both are selected.
Values are CALIBRATED codes. Remove the GUI's manual ADC-code offsets.
Diagnostics are written beside this script, to stream_checked.log.
"""

import argparse
import ctypes
import logging
from pathlib import Path
import queue
import signal
import socket
import threading
import time

import numpy as np
import rp


N = 16384
FS = 125_000_000.0  # STEMlab 125-14
LOG_PATH = Path(__file__).resolve().with_suffix(".log")


def check(name, result):
    code = result[0] if isinstance(result, (tuple, list)) else result
    if code != rp.RP_OK:
        raise RuntimeError(f"{name}: code={code}, {rp.rp_GetError(code)}")
    return result


def value(name, result):
    check(name, result)
    return result[1]


def stats(name, data):
    lo, hi = int(data.min()), int(data.max())
    logging.info("%s: min=%d max=%d span=%d peak_index=%d",
                 name, lo, hi, hi - lo, int(data.argmax()))


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_PATH, mode="w"), logging.StreamHandler()],
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pc-ip", required=True)
    parser.add_argument("--trig-lvl", type=float, required=True)
    parser.add_argument("--trig-dly", type=int, required=True)
    parser.add_argument("--trig-src", choices=("CHA_PE", "CHA_NE", "CHB_PE", "CHB_NE"), required=True)
    parser.add_argument("--dec", type=int, choices=(1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024), required=True)
    parser.add_argument("--mode-ch1", choices=("LV", "HV"), default="HV")
    parser.add_argument("--mode-ch2", choices=("LV", "HV"), default="HV")
    parser.add_argument("--channels", choices=("CH1", "CH2", "CH1+CH2"), required=True)
    args = parser.parse_args()
    logging.info("Settings: %s", vars(args))
    logging.info("rp module: %s; API: %s", getattr(rp, "__file__", "unknown"), rp.rp_GetVersion())

    stop = threading.Event()
    packets = queue.Queue(maxsize=50)
    sender_errors = queue.Queue()
    sock = None
    initialized = False

    def on_signal(signum, frame):
        stop.set()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    try:
        check("rp_Init", rp.rp_Init())
        initialized = True
        check("rp_AcqReset", rp.rp_AcqReset())
        gains = {"LV": rp.RP_LOW, "HV": rp.RP_HIGH}
        check("gain CH1", rp.rp_AcqSetGain(rp.RP_CH_1, gains[args.mode_ch1]))
        check("gain CH2", rp.rp_AcqSetGain(rp.RP_CH_2, gains[args.mode_ch2]))
        check("decimation", rp.rp_AcqSetDecimation(getattr(rp, f"RP_DEC_{args.dec}")))
        trig_channel = rp.RP_T_CH_1 if args.trig_src.startswith("CHA") else rp.RP_T_CH_2
        check("trigger level", rp.rp_AcqSetTriggerLevel(trig_channel, args.trig_lvl))
        check("trigger delay", rp.rp_AcqSetTriggerDelay(args.trig_dly))
        trig_source = getattr(rp, f"RP_TRIG_SRC_{args.trig_src}")

        selected = []
        if args.channels in ("CH1", "CH1+CH2"):
            selected.append(("CH1", rp.RP_CH_1))
        if args.channels in ("CH2", "CH1+CH2"):
            selected.append(("CH2", rp.RP_CH_2))
        storage = {name: rp.i16Buffer(N) for name, channel in selected}
        views = {
            name: np.ctypeslib.as_array(
                ctypes.cast(int(buf.cast()), ctypes.POINTER(ctypes.c_int16)), shape=(N,)
            )
            for name, buf in storage.items()
        }

        sock = socket.create_connection((args.pc_ip, 5000), timeout=5)
        sock.settimeout(5)

        def sender():
            try:
                while not stop.is_set():
                    try:
                        packet = packets.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    sock.sendall(packet.tobytes())
            except Exception as exc:
                logging.exception("TCP sender failed")
                sender_errors.put(exc)
                stop.set()

        thread = threading.Thread(target=sender, daemon=True)
        thread.start()
        frame = 0
        last_log = 0.0
        while not stop.is_set():
            check("disable trigger", rp.rp_AcqSetTriggerSrc(rp.RP_TRIG_SRC_DISABLED))
            check("start", rp.rp_AcqStart())
            # Fill a complete fresh buffer before arming; settings are retained.
            if stop.wait(N * args.dec / FS + 0.001):
                break
            check("arm trigger", rp.rp_AcqSetTriggerSrc(trig_source))
            while not stop.is_set():
                if value("trigger state", rp.rp_AcqGetTriggerState()) == rp.RP_TRIG_STATE_TRIGGERED:
                    break
                stop.wait(0.0001)
            while not stop.is_set():
                if value("buffer fill", rp.rp_AcqGetBufferFillState()):
                    break
                stop.wait(0.0001)
            if stop.is_set():
                break
            check("stop before read", rp.rp_AcqStop())
            pos = value("write pointer", rp.rp_AcqGetWritePointer())
            start = (int(pos) + 1) % N
            frame += 1

            if frame == 1:
                for name, channel in selected:
                    # Sentinel distinguishes an untouched destination from ADC zeros.
                    for i in range(N):
                        storage[name][i] = -30000
                    result = rp.rp_AcqGetOldestDataRaw(channel, N, storage[name].cast())
                    code = result[0] if isinstance(result, (tuple, list)) else result
                    logging.info("ORIGINAL %s rp_AcqGetOldestDataRaw: result=%s error=%s",
                                 name, result, rp.rp_GetError(code))
                    stats("ORIGINAL " + name, views[name])

            now = time.monotonic()
            report = frame <= 3 or now - last_log >= 1.0
            arrays = []
            for name, channel in selected:
                result = check(
                    "calibrated read " + name,
                    rp.rp_AcqGetDataRawWithCalib(channel, start, N, storage[name].cast()),
                )
                if isinstance(result, (tuple, list)) and len(result) > 1 and result[1] != N:
                    raise RuntimeError(f"Short read {name}: {result}")
                data = views[name].copy()
                if report:
                    logging.info("CALIBRATED %s: result=%s", name, result)
                    stats("CALIBRATED " + name, data)
                arrays.append(data)
            if report:
                last_log = now
            packet = arrays[0] if len(arrays) == 1 else np.concatenate(arrays)
            packet = packet.astype("<i2", copy=False)
            try:
                packets.put_nowait(packet)
            except queue.Full:
                logging.warning("Queue full: dropping frame %d", frame)

        if not sender_errors.empty():
            raise RuntimeError("TCP connection failed") from sender_errors.get()
    finally:
        stop.set()
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        if initialized:
            rp.rp_AcqStop()
            rp.rp_Release()
        logging.info("Stopped; log: %s", LOG_PATH)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("Acquisition failed")
        raise SystemExit(1)
