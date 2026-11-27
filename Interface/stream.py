#!/usr/bin/python3

import time
import numpy as np
import rp
import ctypes
import threading
import queue
import socket
import argparse
import os
import signal
import atexit

def _release_rp():
    try:
        rp.rp_Release()
        print("[RP] rp_Release done")
    except Exception as e:
        print(f"[RP] rp_Release error: {e}")

# на любой штатный выход интерпретатора
atexit.register(_release_rp)

# на Ctrl+C (SIGINT) и kill (SIGTERM) — «жёсткий» выход,
# т.к. потоки не daemon и сами не завершатся
def _on_signal(signum, frame):
    print(f"[RP] signal {signum} — shutting down")
    _release_rp()
    os._exit(0)

signal.signal(signal.SIGINT, _on_signal)
signal.signal(signal.SIGTERM, _on_signal)


N = 16384

buffer = queue.Queue(maxsize=50)

parser = argparse.ArgumentParser()

parser.add_argument("--pc-ip")
parser.add_argument("--trig-lvl", type=float)
parser.add_argument("--trig-dly", type=int)
parser.add_argument("--trig-src")
parser.add_argument("--dec", type=int)
parser.add_argument("--mode-ch1", default="HV")   # ⬅ раздельно
parser.add_argument("--mode-ch2", default="HV")
parser.add_argument("--channels")

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



def check_rp(result, operation):
    code = result[0] if isinstance(result, (list, tuple)) else result
    if code != rp.RP_OK:
        raise RuntimeError(f"{operation}: {rp.rp_GetError(code)} (код {code})")
    return result


def acquisition():
    channels = {
        "CH1": (rp.RP_CH_1,),
        "CH2": (rp.RP_CH_2,),
        "CH1+CH2": (rp.RP_CH_1, rp.RP_CH_2),
    }[args.channels]
    adc_buffers = [rp.i16Buffer(N) for _ in channels]

    while True:
        check_rp(
            rp.rp_AcqSetTriggerSrc(rp.RP_TRIG_SRC_DISABLED),
            "Отключение триггера",
        )
        check_rp(rp.rp_AcqStart(), "Запуск захвата")

        # Заполняем буфер свежими отсчётами до включения триггера.
        # 125 МГц — частота АЦП STEMlab 125-14.
        time.sleep(N * args.dec / 125_000_000 + 0.001)
        check_rp(rp.rp_AcqSetTriggerSrc(trig_cmd), "Включение триггера")

        while True:
            state = check_rp(rp.rp_AcqGetTriggerState(), "Состояние триггера")[1]
            if state == rp.RP_TRIG_STATE_TRIGGERED:
                break
            time.sleep(0.0001)

        while not check_rp(rp.rp_AcqGetBufferFillState(), "Заполнение буфера")[1]:
            time.sleep(0.0001)

        check_rp(rp.rp_AcqStop(), "Остановка захвата")
        write_pos = check_rp(rp.rp_AcqGetWritePointer(), "Позиция записи")[1]
        start_pos = (write_pos + 1) % N

        samples = []
        for channel, adc_buffer in zip(channels, adc_buffers):
            result = check_rp(
                rp.rp_AcqGetDataRawWithCalib(
                    channel, start_pos, N, adc_buffer.cast()
                ),
                f"Чтение канала {channel + 1}",
            )
            if result[1] != N:
                raise RuntimeError(f"Прочитано {result[1]} отсчётов вместо {N}")

            ptr = ctypes.cast(
                int(adc_buffer.cast()),
                ctypes.POINTER(ctypes.c_int16),
            )
            samples.append(np.ctypeslib.as_array(ptr, shape=(N,)).copy())

        try:
            buffer.put_nowait(samples[0] if len(samples) == 1 else tuple(samples))
        except queue.Full:
            print("Buffer full, dropping packet")

def sender(sock):

    while True:

        data = buffer.get()

        if args.channels in ("CH1", "CH2"):
            packet = data

        else:
            ch1, ch2 = data
            packet = np.concatenate((ch1,ch2))

        try:
            sock.sendall(packet.tobytes())
        except socket.error as e:
            print(f"Network error: {e} — exiting")
            os._exit(0)     # убить весь процесс, включая acquisition-поток



rp.rp_Init()

rp.rp_AcqReset()

gain1 = MODE_MAP[args.mode_ch1]
gain2 = MODE_MAP[args.mode_ch2]

rp.rp_AcqSetGain(rp.RP_CH_1, gain1)
rp.rp_AcqSetGain(rp.RP_CH_2, gain2)

rp.rp_AcqSetDecimation(
    DEC_MAP[args.dec]
)

# Set trigger level and delay
rp.rp_AcqSetTriggerLevel(TRIGGER_LEVEL_CHANNEL[args.trig_src], args.trig_lvl)
rp.rp_AcqSetTriggerDelay(args.trig_dly)

sock = socket.socket(
    socket.AF_INET,
    socket.SOCK_STREAM
)

sock.connect(
    (args.pc_ip,5000)
)


t1 = threading.Thread(
    target=acquisition   
)

t2 = threading.Thread(
    target=sender,
    args=(sock,)
)


t1.start()
t2.start()