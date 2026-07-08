import socket

HOST = "0.0.0.0"
PORT = 5000

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

sock.settimeout(1.0)   # таймаут 1 секунда

sock.bind((HOST, PORT))
sock.listen(1)

print("Waiting for connection...")


try:
    while True:

        try:
            conn, addr = sock.accept()
            print("Connected:", addr)

            while True:
                data = conn.recv(65536)

                if not data:
                    break

                print("Received:", len(data), "bytes")

        except socket.timeout:
            continue


except KeyboardInterrupt:
    print("Stopping...")

finally:
    sock.close()