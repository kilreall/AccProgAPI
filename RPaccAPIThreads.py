#!/usr/bin/python3

import time
import numpy as np
import rp
import ctypes
import threading
import queue
import socket



N = 16384

ms = 50
buffer = queue.Queue(maxsize=ms)


def acquisition():

    ibuff1 = rp.i16Buffer(N)
    #ibuff2 = rp.i16Buffer(N)

    while True:

        rp.rp_AcqStart()

        rp.rp_AcqSetTriggerSrc(
            rp.RP_TRIG_SRC_CHB_PE
        )

        while not rp.rp_AcqGetBufferFillState()[1]:
            pass


        rp.rp_AcqGetOldestDataRaw(
            rp.RP_CH_1,
            N,
            ibuff1.cast()
        )

        # rp.rp_AcqGetOldestDataRaw(
        #     rp.RP_CH_2,
        #     N,
        #     ibuff2.cast()
        # )

        ptr1 = ctypes.cast(
            int(ibuff1.cast()),
            ctypes.POINTER(ctypes.c_int16)
        )

        ch1 = np.ctypeslib.as_array(
            ptr1,
            shape=(N,)
        ).copy()

        # ch2 = np.ctypeslib.as_array(
        #     ibuff2,
        #     shape=(N,)
        # ).copy()


        buffer.put(
            (ch1)
        )

def sender():

    sock = socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM
    )

    sock.connect(
        ("192.168.55.224",5000)
    )


    while True:

        ch1 = buffer.get()
        #ch1,ch2 = buffer.get()


        # packet = np.concatenate(
        #     (ch1) #,ch2)
        # ).astype(np.int16)
        packet = ch1


        sock.sendall(
            packet.tobytes()
        )


rp.rp_Init()

rp.rp_AcqReset()

rp.rp_AcqSetDecimation(
    rp.RP_DEC_32
)


t1 = threading.Thread(
    target=acquisition
)

t2 = threading.Thread(
    target=sender
)


t1.start()
t2.start()