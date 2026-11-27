import asyncio
import signal
import socket
import struct
import numpy as np
import rp

BUFFER_SIZE = 16384
TRIG_DELAY = -6800


class RedPitayaManager:
    def __init__(self):
        self.client_transports = set()
        self.decimation = rp.RP_DEC_256
        self.trigger_level = 1.5
        self.dac_val = 0.0
        self._loop_task = None
        self._is_running = False

    def register_client(self, transport):
        self.client_transports.add(transport)
        print(f"[RP] Client registered. Total: {len(self.client_transports)}")

    def unregister_client(self, transport):
        self.client_transports.discard(transport)
        print(f"[RP] Client unregistered. Remaining: {len(self.client_transports)}")

    def set_decimation(self, decimation_val: int):
        dec_map = {
            1: rp.RP_DEC_1,
            8: rp.RP_DEC_8,
            64: rp.RP_DEC_64,
            256: rp.RP_DEC_256,
            1024: rp.RP_DEC_1024,
            8192: rp.RP_DEC_8192,
            65536: rp.RP_DEC_65536
        }
        if decimation_val in dec_map:
            self.decimation = dec_map[decimation_val]
            rp.rp_AcqSetDecimation(self.decimation)
            print(f"[RP] Decimation set to: {decimation_val}")
            return True
        return False

    def set_dac(self, dac_val: float):
        self.dac_val = dac_val
        return True

    def start(self):
        print("[RP] Initializing Red Pitaya C-API...")
        rp.rp_Init()
        rp.rp_AcqReset()
        rp.rp_GenReset()

        # Инициализация ЦАП
        rp.rp_GenWaveform(rp.RP_CH_2, rp.RP_WAVEFORM_DC)
        rp.rp_GenAmp(rp.RP_CH_2, self.dac_val)
        rp.rp_GenOutEnable(rp.RP_CH_2)
        rp.rp_GenTriggerOnly(rp.RP_CH_2)

        # Инициализация АЦП
        rp.rp_AcqSetDecimation(self.decimation)
        rp.rp_AcqSetAveraging(True)
        rp.rp_AcqSetGain(rp.RP_CH_1, rp.RP_LOW)
        rp.rp_AcqSetGain(rp.RP_CH_2, rp.RP_HIGH)
        rp.rp_AcqSetTriggerLevel(rp.RP_CH_2, float(self.trigger_level))
        rp.rp_AcqSetTriggerDelay(TRIG_DELAY)

        self._is_running = True
        self._loop_task = asyncio.create_task(self._acquisition_loop())

    def stop(self):
        self._is_running = False
        for t in list(self.client_transports):
            if not t.is_closing():
                t.close()
        self.client_transports.clear()

        if self._loop_task:
            self._loop_task.cancel()
        rp.rp_Release()
        print("[RP] Red Pitaya resources released")

    async def _acquisition_loop(self):
        print("[RP] Acquisition loop started. Waiting for CHB_PE trigger...")

        # Выделяем буферы заранее
        ch1_buff = np.zeros(BUFFER_SIZE, dtype=np.float32)    # np.int16)
        ch2_buff = np.zeros(BUFFER_SIZE, dtype=np.float32)    # np.int16)

        while self._is_running:
            # 1. Запуск сброса и установки триггера
            rp.rp_AcqStart()
            rp.rp_AcqSetTriggerSrc(rp.RP_TRIG_SRC_DISABLED)
            rp.rp_AcqSetTriggerSrc(rp.RP_TRIG_SRC_CHB_PE)

            # 2. Ожидание заполнения буфера
            while self._is_running:
                await asyncio.sleep(0.0005)  # Не блокируем event loop
                if rp.rp_AcqGetBufferFillState()[1]:
                    break

            if not self._is_running:
                break

            # 3. Считывание сырых данных начиная с позиции триггера
            rp.rp_AcqGetLatestDataVNP(rp.RP_CH_1, ch1_buff)
            rp.rp_AcqGetLatestDataVNP(rp.RP_CH_2, ch2_buff)

            # 4. Если клиенты подключены — рассылаем пакет
            if self.client_transports:
                # print('data sent')
                payload = ch1_buff.tobytes() + ch2_buff.tobytes()
                header = struct.pack('!I', len(payload))
                packet = header + payload

                for transport in list(self.client_transports):
                    if not transport.is_closing():
                        transport.write(packet)

            # 5. Устанавливаем сигнал на DAC
            rp.rp_GenAmp(rp.RP_CH_2, self.dac_val)
            rp.rp_GenOutEnable(rp.RP_CH_2)
            rp.rp_GenTriggerOnly(rp.RP_CH_2)


class TCPClientHandler(asyncio.Protocol):
    def __init__(self, rp_manager: RedPitayaManager):
        self.rp_manager = rp_manager
        self.transport = None
        self.buffer = b''

    def connection_made(self, transport):
        self.transport = transport
        print("[TCP] Client connected")
        sock = transport.get_extra_info('socket')
        if sock:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.rp_manager.register_client(self.transport)

    def connection_lost(self, exc):
        print("[TCP] Client disconnected")
        self.rp_manager.unregister_client(self.transport)

    def data_received(self, data):
        self.buffer += data
        while b';' in self.buffer:
            raw_msg, self.buffer = self.buffer.split(b';', 1)
            message = raw_msg.decode().strip()
            if not message:
                continue

            print(f"[TCP] Command received: {message}")
            parts = message.split(':')
            if len(parts) == 3 and parts[0] == 'SET':
                param, value = parts[1], parts[2]
                if param == 'DEC':
                    try:
                        dec_val = int(value)
                        if self.rp_manager.set_decimation(dec_val):
                            self.transport.write(f"OK:DEC={dec_val}\n".encode())
                        else:
                            self.transport.write(b"ERROR: Invalid decimation value\n")
                    except ValueError:
                        self.transport.write(b"ERROR: Decimation must be integer\n")
                elif param == 'DAC':
                    try:
                        out_val = float(value)
                        if self.rp_manager.set_dac(out_val):
                            print(f"OK:DAC={out_val}")
                            # self.transport.write(f"OK:DAC={out_val}\n".encode())
                        else:
                            self.transport.write(b"ERROR: Invalid DAC value\n")
                    except ValueError:
                        self.transport.write(b"ERROR: Invalid DAC value\n")
                else:
                    self.transport.write(f"ERROR: Unknown parameter '{param}'\n".encode())
            else:
                self.transport.write(b"ERROR: Invalid command format. Use SET:PARAM:VALUE;\n")


async def main():
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    PORT = 9999
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, 'SO_REUSEPORT'):
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)

    server_sock.bind(('0.0.0.0', PORT))
    server_sock.setblocking(False)

    rp_manager = RedPitayaManager()
    rp_manager.start()

    def shutdown_signal_handler():
        print("\n[Main] Shutdown signal received.")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown_signal_handler)
        except NotImplementedError:
            pass

    server = await loop.create_server(
        lambda: TCPClientHandler(rp_manager),
        sock=server_sock
    )

    print(f"[TCP] Server listening on port {PORT}...")
    try:
        await stop_event.wait()
    finally:
        server.close()
        await server.wait_closed()
        rp_manager.stop()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass