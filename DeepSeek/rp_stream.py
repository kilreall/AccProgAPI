#!/usr/bin/python3
"""
Минимальный стример для Red Pitaya
"""

import time
import numpy as np
import rp
import ctypes
import socket
import struct
import signal
import sys

N = 16384
DATA_PORT = 5000
HEADER_MAGIC = 0x52503031

# Глобальные переменные
running = True

def signal_handler(sig, frame):
    global running
    print("\nStopping...")
    running = False

def main():
    global running
    
    signal.signal(signal.SIGINT, signal_handler)
    
    print("Initializing RP...")
    if rp.rp_Init() != rp.RP_OK:
        print("Failed to initialize!")
        sys.exit(1)
    
    print(f"RP Version: {rp.rp_GetVersion()}")
    
    # Настройка RP
    rp.rp_AcqReset()
    rp.rp_AcqSetDecimation(rp.RP_DEC_1024)
    rp.rp_AcqSetGain(rp.RP_CH_1, rp.RP_HIGH)
    rp.rp_AcqSetGain(rp.RP_CH_2, rp.RP_HIGH)
    rp.rp_AcqSetTriggerSrc(rp.RP_TRIG_SRC_CHB_PE)
    rp.rp_AcqSetTriggerLevel(rp.RP_CH_2, 1.25)
    rp.rp_AcqSetTriggerDelay(8100)
    
    # Буферы
    ibuff1 = rp.i16Buffer(N)
    ibuff2 = rp.i16Buffer(N)
    
    # Подключение к ПК
    pc_ip = '192.168.55.224'  # ИЗМЕНИТЕ НА ВАШ IP!
    
    print(f"Connecting to {pc_ip}:{DATA_PORT}...")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    
    while running:
        try:
            sock.connect((pc_ip, DATA_PORT))
            print("Connected!")
            break
        except Exception as e:
            print(f"Connection failed: {e}, retrying...")
            time.sleep(2)
    
    packet_count = 0
    
    while running:
        try:
            # Запуск сбора
            rp.rp_AcqStart()
            
            # Ожидание триггера
            while running:
                trig_state = rp.rp_AcqGetTriggerState()[1]
                if trig_state == rp.RP_TRIG_STATE_TRIGGERED:
                    break
                time.sleep(0.0001)
            
            if not running:
                break
            
            # Ожидание заполнения буфера
            while running:
                if rp.rp_AcqGetBufferFillState()[1]:
                    break
                time.sleep(0.0001)
            
            if not running:
                break
            
            # Чтение данных
            rp.rp_AcqGetOldestDataRaw(rp.RP_CH_1, N, ibuff1.cast())
            rp.rp_AcqGetOldestDataRaw(rp.RP_CH_2, N, ibuff2.cast())
            
            # Конвертация
            ptr1 = ctypes.cast(int(ibuff1.cast()), ctypes.POINTER(ctypes.c_int16))
            ptr2 = ctypes.cast(int(ibuff2.cast()), ctypes.POINTER(ctypes.c_int16))
            
            ch1 = np.ctypeslib.as_array(ptr1, shape=(N,)).copy()
            ch2 = np.ctypeslib.as_array(ptr2, shape=(N,)).copy()
            
            # Формирование пакета
            payload = np.concatenate((ch1, ch2)).astype(np.int16)
            payload_bytes = payload.tobytes()
            
            # Заголовок
            header = struct.pack("<IIII", HEADER_MAGIC, len(payload_bytes), packet_count, 0)
            
            # Отправка
            sock.sendall(header)
            sock.sendall(payload_bytes)
            
            packet_count += 1
            if packet_count % 10 == 0:
                print(f"Sent {packet_count} packets")
                
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(0.1)
    
    # Очистка
    sock.close()
    rp.rp_AcqStop()
    rp.rp_AcqReset()
    rp.rp_Release()
    print("Done!")

if __name__ == "__main__":
    main()