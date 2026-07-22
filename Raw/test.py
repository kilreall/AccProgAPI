#!/usr/bin/python3

import time
import numpy as np
import rp
import ctypes
import threading
import queue
import socket
import argparse

N = 16384

rp.rp_Init()
rp.rp_AcqReset()
rp.rp_AcqSetDecimation(rp.RP_DEC_64)
rp.rp_AcqSetGain(rp.RP_CH_1, rp.RP_HIGH)
rp.rp_AcqSetGain(rp.RP_CH_2, rp.RP_HIGH)
rp.rp_AcqSetTriggerLevel(rp.RP_T_CH_2, 1.0)
rp.rp_AcqSetTriggerDelay(8192)


ibuff1 = rp.i16Buffer(N)

while True:

    rp.rp_AcqStart()

    # запуск триггера
    rp.rp_AcqSetTriggerSrc(rp.RP_TRIG_SRC_CHB_PE)

    t0 = time.perf_counter()

    # ждать именно триггер
    while 1:
        trig_state = rp.rp_AcqGetTriggerState()[1]
        if trig_state == rp.RP_TRIG_STATE_TRIGGERED:
            break

    # ждать заполнение после триггера
    while not rp.rp_AcqGetBufferFillState()[1]:
        pass

    # rp.rp_AcqGetOldestDataRaw(
    #     rp.RP_CH_2,
    #     N,
    #     ibuff1.cast()
    # )

    trig_pos = rp.rp_AcqGetWritePointerAtTrig()[1]

    print("trigger position:", trig_pos)

    start = (trig_pos - N//2) % N

    rp.rp_AcqGetDataRaw(
        rp.RP_CH_2,
        start,
        N,
        ibuff1.cast()
    )

    ptr1 = ctypes.cast(
    int(ibuff1.cast()),
    ctypes.POINTER(ctypes.c_int16)
    )


    ch1 = np.ctypeslib.as_array(
        ptr1,
        shape=(N,)
    ).copy()


    dt = (time.perf_counter() - t0) * 1e3
    print(f"t_fill = {dt:.2f} ms")
    print(ch1.min(), ch1.max())
    print(ch1[:20])



