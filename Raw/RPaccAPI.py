#!/usr/bin/python3

import time
import numpy as np
import rp
import ctypes
import threading
import queue
import socket


while 1:

    channel1 = rp.RP_CH_1
    channel2 = rp.RP_CH_2



    #? Possible decimations:
    #?  RP_DEC_1, RP_DEC_2, RP_DEC_4, RP_DEC_8, RP_DEC_16 , RP_DEC_32 , RP_DEC_64 ,
    #?  RP_DEC_128, RP_DEC_256, RP_DEC_512, RP_DEC_1024, RP_DEC_2048, RP_DEC_4096, RP_DEC_8192,
    #?  RP_DEC_16384, RP_DEC_32768, RP_DEC_65536

    dec = rp.RP_DEC_32

    trig_lvl = 0.1
    trig_dly = 8100

    #? Possible acquisition trigger sources:
    #?  RP_TRIG_SRC_DISABLED, RP_TRIG_SRC_NOW, RP_TRIG_SRC_CHA_PE, RP_TRIG_SRC_CHA_NE, RP_TRIG_SRC_CHB_PE,
    #?  RP_TRIG_SRC_CHB_NE, RP_TRIG_SRC_EXT_PE, RP_TRIG_SRC_EXT_NE, RP_TRIG_SRC_AWG_PE, RP_TRIG_SRC_AWG_NE,
    #?  RP_TRIG_SRC_CHC_PE, RP_TRIG_SRC_CHC_NE, RP_TRIG_SRC_CHD_PE, RP_TRIG_SRC_CHD_NE

    #acq_trig_sour = rp.RP_TRIG_SRC_NOW
    acq_trig_sour = rp.RP_TRIG_SRC_CHB_PE
    N = 16384

    # Initialize the interface
    rp.rp_Init()

    # Reset Generation and Acquisition
    rp.rp_AcqReset()


    ##### Acquisition #####
    # Set Decimation
    rp.rp_AcqSetDecimation(dec)

    #? Possible triggers:
    #?  RP_T_CH_1, RP_T_CH_2, RP_T_CH_EXT

    # Set trigger level and delay
    rp.rp_AcqSetTriggerLevel(rp.RP_T_CH_2, trig_lvl)
    rp.rp_AcqSetTriggerDelay(trig_dly)

    workFlag = 1

    if workFlag == 1:
        ij = 0
        V_m = []
        print("Acquisition started")   
        ibuff = rp.i16Buffer(N)
        # fbuff = rp.fBuffer(N)
        # ptr = ctypes.cast(
        #     int(fbuff.this),
        #     ctypes.POINTER(ctypes.c_float)
        # )
        data_V = np.zeros(N, dtype = float)


    while workFlag == 1:

        t01 = time.perf_counter()
        rp.rp_AcqStart()
        t02 = time.perf_counter()
        print("0", (t02-t01)*1e3)

        # Specify trigger - input 1 positive edge
        t11 = time.perf_counter()
        rp.rp_AcqSetTriggerSrc(acq_trig_sour)
        t12 = time.perf_counter()
        print("1", (t12-t11)*1e3)

        #rp.rp_GenTriggerOnly(channel1)       # Trigger generator

        # Trigger state
        # while 1:
        #     trig_state = rp.rp_AcqGetTriggerState()[1]
        #     if trig_state == rp.RP_TRIG_STATE_TRIGGERED:
        #         break

        ## ! OS 2.00 or higher only ! ##
        # Fill state
        t21 = time.perf_counter()
        while 1:
            if rp.rp_AcqGetBufferFillState()[1]:
                #print("Trigger")
                break
        t22 = time.perf_counter()
        print("2", (t22-t21)*1e3)

        if ij > 0:
            t2 = t1
            t1 = time.time()
            dt1 = t1 - t2
            print("point1", dt1*1e3)
        else:
            t1 = time.time()

        # Get data
        
        #res = rp.rp_AcqGetOldestDataRaw(rp.RP_CH_1, N, ibuff.cast())

        #fbuff = rp.fBuffer(N)
        t31 = time.perf_counter()
        #res = rp.rp_AcqGetDataV(rp.RP_CH_1, 0, N, fbuff)
        res = rp.rp_AcqGetOldestDataRaw(rp.RP_CH_1, N, ibuff.cast())
        t32 = time.perf_counter()
        print("3", (t32-t31)*1e3)

        #data_V = np.zeros(N, dtype = float)
        #data_raw = np.zeros(N, dtype = int)

        t41 = time.perf_counter()
        #data_V = np.ctypeslib.as_array(ptr, shape=(N,))
        t42 = time.perf_counter()
        print("4", (t42-t41)*1e3)



        #print(f"Data in Volts: {data_V}")
        #V_m.append(data_V)
        #print(ij)
        #if ij == 10:
        #    break

        ij += 1
    

    # Release resources
    print("Release")
    #V_m = np.array(V_m)
    #np.save("V_m.npy", V_m)
    rp.rp_Release()
    break