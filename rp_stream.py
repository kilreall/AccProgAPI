#!/usr/bin/python3

import argparse
import ctypes
import queue
import signal
import socket
import struct
import threading
import time

import numpy as np
import rp

##############################################################################
# Constants
##############################################################################

N = 16384

HEADER_MAGIC = 0x52503031      # "RP01"

MODE_TRIGGER = 0
MODE_CONTINUOUS = 1

DECIMATION = {
    1: rp.RP_DEC_1,
    2: rp.RP_DEC_2,
    4: rp.RP_DEC_4,
    8: rp.RP_DEC_8,
    16: rp.RP_DEC_16,
    64: rp.RP_DEC_64,
    1024: rp.RP_DEC_1024,
    8192: rp.RP_DEC_8192,
    65536: rp.RP_DEC_65536,
}

##############################################################################
# Command line
##############################################################################

parser = argparse.ArgumentParser()

parser.add_argument(
    "--host",
    required=True,
    help="Receiver IP"
)

parser.add_argument(
    "--port",
    type=int,
    default=5000
)

parser.add_argument(
    "--mode",
    choices=["trigger", "continuous"],
    default="trigger"
)

parser.add_argument(
    "--dec",
    type=int,
    default=1024
)

parser.add_argument(
    "--gain",
    default="HV"
)

parser.add_argument(
    "--trigger",
    type=float,
    default=1.25
)

parser.add_argument(
    "--delay",
    type=int,
    default=8100
)

args = parser.parse_args()

##############################################################################
# Global objects
##############################################################################

stop_event = threading.Event()

packet_queue = queue.Queue(maxsize=100)

packet_counter = 0

##############################################################################
# Signals
##############################################################################

def stop_handler(sig, frame):
    print("Stopping...")
    stop_event.set()

signal.signal(signal.SIGTERM, stop_handler)
signal.signal(signal.SIGINT, stop_handler)

##############################################################################
# Acquisition Thread
##############################################################################

class AcquisitionThread(threading.Thread):

    def __init__(self):
        super().__init__(daemon=True)

        self.ibuff1 = rp.i16Buffer(N)
        self.ibuff2 = rp.i16Buffer(N)

    def run(self):

        global packet_counter

        while not stop_event.is_set():

            rp.rp_AcqStart()

            if args.mode == "trigger":

                rp.rp_AcqSetTriggerSrc(
                    rp.RP_TRIG_SRC_CHB_PE
                )

                while (
                    not stop_event.is_set()
                    and
                    not rp.rp_AcqGetBufferFillState()[1]
                ):
                    pass

            else:

                while (
                    not stop_event.is_set()
                    and
                    not rp.rp_AcqGetBufferFillState()[1]
                ):
                    pass

            if stop_event.is_set():
                break

            rp.rp_AcqGetOldestDataRaw(
                rp.RP_CH_1,
                N,
                self.ibuff1.cast()
            )

            rp.rp_AcqGetOldestDataRaw(
                rp.RP_CH_2,
                N,
                self.ibuff2.cast()
            )

            ptr1 = ctypes.cast(
                int(self.ibuff1.cast()),
                ctypes.POINTER(ctypes.c_int16)
            )

            ptr2 = ctypes.cast(
                int(self.ibuff2.cast()),
                ctypes.POINTER(ctypes.c_int16)
            )

            ch1 = np.ctypeslib.as_array(
                ptr1,
                shape=(N,)
            ).copy()

            ch2 = np.ctypeslib.as_array(
                ptr2,
                shape=(N,)
            ).copy()

            packet_counter += 1

            try:

                packet_queue.put_nowait(
                    (
                        packet_counter,
                        ch1,
                        ch2
                    )
                )

            except queue.Full:
                print("Queue overflow")

##############################################################################
# Sender Thread
##############################################################################

class SenderThread(threading.Thread):

    def __init__(self):
        super().__init__(daemon=True)

        self.sock = None

    ##########################################################################

    def connect(self):

        while not stop_event.is_set():

            try:

                print(
                    f"Connecting to {args.host}:{args.port}..."
                )

                self.sock = socket.socket(
                    socket.AF_INET,
                    socket.SOCK_STREAM
                )

                self.sock.setsockopt(
                    socket.IPPROTO_TCP,
                    socket.TCP_NODELAY,
                    1
                )

                self.sock.connect(
                    (
                        args.host,
                        args.port
                    )
                )

                print("Connected.")

                return

            except Exception as e:

                print(
                    "Connection failed:",
                    e
                )

                time.sleep(1)

    ##########################################################################

    def run(self):

        self.connect()

        while not stop_event.is_set():

            try:

                packet_id, ch1, ch2 = packet_queue.get(
                    timeout=0.2
                )

            except queue.Empty:
                continue

            mode = (
                MODE_TRIGGER
                if args.mode == "trigger"
                else MODE_CONTINUOUS
            )

            ##################################################################
            # Packet
            ##################################################################

            payload = np.concatenate(
                (
                    ch1,
                    ch2
                )
            ).astype(np.int16)

            header = struct.pack(
                "<IIII",
                HEADER_MAGIC,
                payload.nbytes,
                packet_id,
                mode
            )

            try:

                self.sock.sendall(header)
                self.sock.sendall(
                    payload.tobytes()
                )

            except Exception as e:

                print(
                    "Connection lost:",
                    e
                )

                try:
                    self.sock.close()
                except:
                    pass

                self.connect()

##############################################################################
# RP initialization
##############################################################################

print("Initializing RP...")

rp.rp_Init()

rp.rp_AcqReset()

###########################################################################
# Decimation
###########################################################################

if args.dec not in DECIMATION:

    raise RuntimeError(
        f"Unsupported decimation {args.dec}"
    )

rp.rp_AcqSetDecimation(
    DECIMATION[
        args.dec
    ]
)

###########################################################################
# Gain
###########################################################################

#
# Здесь будет настройка gain,
# когда определим API вашей версии librp
#
#
# например
#
# rp.rp_AcqSetGain(...)
#
#

###########################################################################
# Trigger level
###########################################################################

#
# Здесь позже будет
#
# rp.rp_AcqSetTriggerLevel(...)
#
#

###########################################################################
# Trigger delay
###########################################################################

#
# Здесь позже будет
#
# rp.rp_AcqSetTriggerDelay(...)
#
#


##############################################################################
# Main
##############################################################################

def main():

    print("-------------------------------------")
    print(" Red Pitaya streaming server")
    print("-------------------------------------")
    print(f"Mode       : {args.mode}")
    print(f"Receiver   : {args.host}:{args.port}")
    print(f"Decimation : {args.dec}")
    print(f"Trigger    : {args.trigger}")
    print(f"Delay      : {args.delay}")
    print("-------------------------------------")

    acquisition = AcquisitionThread()
    sender = SenderThread()

    acquisition.start()
    sender.start()

    try:

        while not stop_event.is_set():

            time.sleep(0.2)

    finally:

        print("Stopping threads...")

        stop_event.set()

        acquisition.join()

        sender.join()

        try:

            sender.sock.shutdown(socket.SHUT_RDWR)

        except:
            pass

        try:

            sender.sock.close()

        except:
            pass

        try:

            rp.rp_AcqStop()

        except:
            pass

        try:

            rp.rp_AcqReset()

        except:
            pass

        try:

            rp.rp_Release()

        except:
            pass

        print("Finished.")


##############################################################################

if __name__ == "__main__":

    main()