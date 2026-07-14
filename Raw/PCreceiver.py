import socket
import numpy as np
import time

HOST = "0.0.0.0"
PORT = 5000
N = 16384  # Размер одного пакета (как на Red Pitaya)
PACKET_BYTES = N * 2  # 32768 байт


sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

sock.settimeout(1.0)   # таймаут 1 секунда

sock.bind((HOST, PORT))
sock.listen(1)

print("Waiting for connection...")
all_data = []


try:
    while True:

        try:
            conn, addr = sock.accept()
            print("Connected:", addr)
            buffer = bytearray()

            while True:
                tr = time.perf_counter()
                data = conn.recv(65536)
                print("tr", (time.perf_counter()-tr)*1e3)

                if not data:
                    break
                
                buffer.extend(data)
                while len(buffer) >= PACKET_BYTES:

                    packet_bytes = buffer[:PACKET_BYTES]
                    buffer = buffer[PACKET_BYTES:]
                    packet_data = np.frombuffer(packet_bytes, dtype=np.int16)
                    all_data.append(packet_data)
    
                print("Received:", len(data), "bytes")

        except socket.timeout:
            continue


except KeyboardInterrupt:
    print("Stopping...")
    np.savez_compressed("data.npz", msts=np.array(all_data))
finally:
    sock.close()