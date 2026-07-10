#!/usr/bin/python3

import time
import numpy as np
import rp
import ctypes
import threading
import queue
import socket



N = 16384


buffer = queue.Queue(maxsize=50)


def acquisition():

    ibuff1 = rp.i16Buffer(N)
    #ibuff2 = rp.i16Buffer(N)

    while True:

        #t1 = time.perf_counter()
        rp.rp_AcqStart()
        #print("t1", (time.perf_counter() - t1)*1e3)

        #t2 = time.perf_counter()
        rp.rp_AcqSetTriggerSrc(
            rp.RP_TRIG_SRC_CHB_PE
        )
        #print("t2", (time.perf_counter() - t2)*1e3)

        while not rp.rp_AcqGetBufferFillState()[1]:
            pass

        #t3 = time.perf_counter()
        rp.rp_AcqGetOldestDataRaw(
            rp.RP_CH_1,
            N,
            ibuff1.cast()
        )
        #print("t3", (time.perf_counter() - t3)*1e3)

        # rp.rp_AcqGetOldestDataRaw(
        #     rp.RP_CH_2,
        #     N,
        #     ibuff2.cast()
        # )

        #t4 = time.perf_counter()
        ptr1 = ctypes.cast(
            int(ibuff1.cast()),
            ctypes.POINTER(ctypes.c_int16)
        )
        #print("t4", (time.perf_counter() - t4)*1e3)

        #t5 = time.perf_counter()
        ch1 = np.ctypeslib.as_array(
            ptr1,
            shape=(N,)
        ).copy()
        
        #print("t5", (time.perf_counter() - t5)*1e3)

        # ch2 = np.ctypeslib.as_array(
        #     ibuff2,
        #     shape=(N,)
        # ).copy()

        
        try:
            #t6 = time.perf_counter()
            buffer.put_nowait((ch1))
            #print("t6", (time.perf_counter() - t6)*1e3)
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
    rp.RP_DEC_1024
)


t1 = threading.Thread(
    target=acquisition
)

t2 = threading.Thread(
    target=sender
)


t1.start()
t2.start()