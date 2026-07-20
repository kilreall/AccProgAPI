#!/usr/bin/python3


import time
import rp

N = 16384

rp.rp_Init()
rp.rp_AcqReset()
rp.rp_AcqSetDecimation(rp.RP_DEC_64)
rp.rp_AcqSetTriggerLevel(rp.RP_T_CH_2, 0.1)
rp.rp_AcqSetTriggerDelay(8192)

while True:

    rp.rp_AcqStart()

    # запуск триггера
    rp.rp_AcqSetTriggerSrc(rp.RP_TRIG_SRC_CHB_PE)

    t0 = time.perf_counter()

    # ждать именно триггер
    while rp.rp_AcqGetTriggerState()[1] != rp.RP_TRIG_STATE_TRIGGERED:
        pass

    # ждать заполнение после триггера
    while not rp.rp_AcqGetBufferFillState()[1]:
        pass

    dt = (time.perf_counter() - t0) * 1e3
    print(f"t_fill = {dt:.2f} ms")



