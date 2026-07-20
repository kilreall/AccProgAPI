#!/usr/bin/python3

import time
import numpy as np
import rp
import ctypes
import threading
import queue
import socket



N = 16384
trig_lvl = 0.1
trig_dly = 8192

buffer = queue.Queue(maxsize=50)


def acquisition():

    ibuff1 = rp.i16Buffer(N)
    #ibuff2 = rp.i16Buffer(N)
    ij = 0
    while True:

        if ij == 0:
            ts = time.perf_counter()
        if ij > 0:
            tf = time.perf_counter()
            print(f"dt_acq{(ts - tf)*1e3} ms")
            ts = tf
        ij += 1

        # tre = time.perf_counter()
        # rp.rp_AcqReset()
        # print("treset", (time.perf_counter() - tre)*1e3)

        # tdec = time.perf_counter()
        # rp.rp_AcqSetDecimation(
        #     rp.RP_DEC_512
        # )
        # print("tdec", (time.perf_counter() - tre)*1e3)

        t1 = time.perf_counter()
        rp.rp_AcqStart()
        print("tstart", (time.perf_counter() - t1)*1e3)

        t2 = time.perf_counter()
        rp.rp_AcqSetTriggerSrc(rp.RP_TRIG_SRC_CHB_PE)
        #rp.rp_GenTriggerOnly(rp.RP_CH_1)       # Trigger generator
        print("tsettriger", (time.perf_counter() - t2)*1e3)

        tt = time.perf_counter()
        while 1:
            trig_state = rp.rp_AcqGetTriggerState()[1]
            if trig_state == rp.RP_TRIG_STATE_TRIGGERED:
                break

        while not rp.rp_AcqGetBufferFillState()[1]:
            pass
        print("tbuffer", (time.perf_counter() - tt)*1e3)

        t3 = time.perf_counter()
        rp.rp_AcqGetOldestDataRaw(
            rp.RP_CH_1,
            N,
            ibuff1.cast()
        )
        print("tgetbuffer", (time.perf_counter() - t3)*1e3)

        # rp.rp_AcqGetOldestDataRaw(
        #     rp.RP_CH_2,
        #     N,
        #     ibuff2.cast()
        # )

        t4 = time.perf_counter()
        ptr1 = ctypes.cast(
            int(ibuff1.cast()),
            ctypes.POINTER(ctypes.c_int16)
        )
        print("t4", (time.perf_counter() - t4)*1e3)

        t5 = time.perf_counter()
        ch1 = np.ctypeslib.as_array(
            ptr1,
            shape=(N,)
        ).copy()
        
        print("t5", (time.perf_counter() - t5)*1e3)

        # ch2 = np.ctypeslib.as_array(
        #     ibuff2,
        #     shape=(N,)
        # ).copy()

        t6 = time.perf_counter()
        try:
            buffer.put_nowait((ch1))
            print("tsend", (time.perf_counter() - t6)*1e3)
        except queue.Full:
            print("Buffer full, dropping packet")
            # Или: buffer.get() # удалить самый старый пакет
            # Или: увеличить размер буфера

        

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

        
        try:
            #ts = time.perf_counter()
            sock.sendall(packet.tobytes())
            #print("ts", (time.perf_counter()-ts)*1e3)
        except socket.error as e:
            print(f"Network error: {e}")
            # Сохранить данные или переподключиться


rp.rp_Init()

rp.rp_AcqReset()

rp.rp_AcqSetDecimation(
    rp.RP_DEC_512
)

# Set trigger level and delay
rp.rp_AcqSetTriggerLevel(rp.RP_T_CH_2, trig_lvl)
rp.rp_AcqSetTriggerDelay(trig_dly)

t1 = threading.Thread(
    target=acquisition
)

t2 = threading.Thread(
    target=sender
)


t1.start()
t2.start()