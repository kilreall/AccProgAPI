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


buffer = queue.Queue(maxsize=50)

parser = argparse.ArgumentParser()

parser.add_argument("--pc-ip")
parser.add_argument("--trig-lvl", type=float)
parser.add_argument("--trig-dly", type=int)
parser.add_argument("--trig-src")
parser.add_argument("--dec", type=int)
parser.add_argument("--mode")

args = parser.parse_args()

TRIGGER_MAP = {
    "CHA_PE": rp.RP_TRIG_SRC_CHA_PE,
    "CHA_NE": rp.RP_TRIG_SRC_CHA_NE,
    "CHB_PE": rp.RP_TRIG_SRC_CHB_PE,
    "CHB_NE": rp.RP_TRIG_SRC_CHB_NE,
}

trig_cmd = TRIGGER_MAP[args.trig_src]

TRIGGER_LEVEL_CHANNEL = {
    "CHA_PE": rp.RP_T_CH_1,
    "CHA_NE": rp.RP_T_CH_1,
    "CHB_PE": rp.RP_T_CH_2,
    "CHB_NE": rp.RP_T_CH_2,
}

MODE_MAP = {
    "HV": rp.RP_HIGH,
    "LV": rp.RP_LOW,
}

DEC_MAP = {
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
}


trig_lvl = args.trig_lvl
trig_dly = args.trig_dly

def acquisition():

    ibuff1 = rp.i16Buffer(N)
    #ibuff2 = rp.i16Buffer(N)

    

    while True:


        rp.rp_AcqStart()

        rp.rp_AcqSetTriggerSrc(
            trig_cmd
        )

        # Trigger state
        while 1:
            trig_state = rp.rp_AcqGetTriggerState()[1]
            if trig_state == rp.RP_TRIG_STATE_TRIGGERED:
                break

        # Trigger fill
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

        
        try:
            buffer.put_nowait((ch1))
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
        (args.pc_ip,5000)
    )


    while True:

        ch1 = buffer.get()
        #ch1,ch2 = buffer.get()


        # packet = np.concatenate(
        #     (ch1) #,ch2)
        # ).astype(np.int16)
        packet = ch1

        
        try:
            sock.sendall(packet.tobytes())
        except socket.error as e:
            print(f"Network error: {e}")
            # Сохранить данные или переподключиться


rp.rp_Init()

rp.rp_AcqReset()

gain = MODE_MAP[args.mode]

rp.rp_AcqSetGain(rp.RP_CH_1, gain)
rp.rp_AcqSetGain(rp.RP_CH_2, gain)

rp.rp_AcqSetDecimation(
    DEC_MAP[args.dec]
)

# Set trigger level and delay
rp.rp_AcqSetTriggerLevel(TRIGGER_LEVEL_CHANNEL[args.trig_src], trig_lvl)
rp.rp_AcqSetTriggerDelay(trig_dly)

t1 = threading.Thread(
    target=acquisition
)

t2 = threading.Thread(
    target=sender
)


t1.start()
t2.start()