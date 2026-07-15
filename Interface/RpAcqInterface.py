from PyQt5.QtCore import QRunnable, QThreadPool, pyqtSlot, QObject, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication, QWidget, QPushButton, QVBoxLayout, QLineEdit,
    QLabel, QSpinBox, QDoubleSpinBox, QHBoxLayout, QFileDialog
)
from datetime import datetime
import sys, time, random, os, socket, paramiko
import numpy as np
import pyqtgraph as pg
pg.setConfigOption('background', 'w')
pg.setConfigOption('foreground', 'k')

N = 16384
PACKET_BYTES = N * 2

# ---------- Continuous mode (SCPI) – без изменений ----------
class ContinuousWorkerSignals(QObject):
    finished = pyqtSignal()
    data = pyqtSignal(np.ndarray)

class ContinuousWorker(QRunnable):
    def __init__(self, ip, dec):
        super().__init__()
        self.ip = ip
        self.dec = dec
        self.signals = ContinuousWorkerSignals()
        self._is_running = True

    @pyqtSlot()
    def run(self):
        print("Continuous mode started")
        import scpi
        rp = scpi.scpi(self.ip)
        rp.tx_txt('ACQ:RST')
        rp.tx_txt(f"ACQ:DEC:Factor {self.dec}")
        rp.tx_txt('ACQ:DATA:Units VOLTS')
        rp.tx_txt('ACQ:DATA:FORMAT ASCII')
        rp.tx_txt('ACQ:SOUR1:GAIN HV')
        while self._is_running:
            rp.tx_txt('ACQ:START')
            rp.tx_txt('ACQ:TRig NOW')
            while True:
                rp.tx_txt('ACQ:TRig:STAT?')
                if rp.rx_txt() == 'TD':
                    break
            rp.tx_txt('ACQ:SOUR1:DATA?')
            buff_string = rp.rx_txt()
            buff = np.array(buff_string.strip('{}\n\r ').replace("  ", "").split(','), dtype=np.float64)
            self.signals.data.emit(buff)
        rp.tx_txt('ACQ:RST')
        print("Continuous mode stopped")
        self.signals.finished.emit()

    def stop(self):
        self._is_running = False

# ---------- Trigger mode (SSH + TCP) – обновлён под ваш скрипт ----------
class TriggerWorkerSignals(QObject):
    finished = pyqtSignal()
    data = pyqtSignal(np.ndarray)

class TriggerWorker(QRunnable):
    def __init__(self, rp_ip, save_path):
        super().__init__()
        self.rp_ip = rp_ip
        self.data_port = 5000
        self.ssh_user = "root"
        self.ssh_pass = "root"
        self.save_path = save_path
        self.signals = TriggerWorkerSignals()
        self._is_running = True
        self.all_data = []
        self.client = None
        self.stdin = None
        self.stdout = None
        self.stderr = None

        self.server_sock = None
        self.conn = None

    def start_remote_stream(self):

        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(
            paramiko.AutoAddPolicy()
        )

        self.client.connect(
            self.rp_ip,
            username=self.ssh_user,
            password=self.ssh_pass,
            timeout=5
        )

        cmd = "PYTHONPATH=/opt/redpitaya/lib/python:$PYTHONPATH /usr/bin/python3 /root/stream.py"

        self.stdin, self.stdout, self.stderr = \
            self.client.exec_command(cmd)

        print("Remote stream started.")

    def wait_connection(self):

        print("Waiting for RedPitaya...")

        self.conn, addr = self.server_sock.accept()

        print(f"Connected from {addr}")
        

    def receive_loop(self):

        buffer = bytearray()

        while self._is_running:

            data = self.conn.recv(65536)

            if not data:
                break

            buffer.extend(data)

            while len(buffer) >= PACKET_BYTES:

                packet = np.frombuffer(
                    buffer[:PACKET_BYTES],
                    dtype=np.int16
                )

                buffer = buffer[PACKET_BYTES:]

                self.all_data.append(packet.copy())

                ch1 = (
                    packet.astype(np.float32) + 168
                ) / 8191 * 20

                self.signals.data.emit(ch1)

    def cleanup(self):

        if self.conn:
            self.conn.close()

        if self.server_sock:
            self.server_sock.close()

        if self.client:
            self.client.close()

    @pyqtSlot()
    def run(self):

        self.server_sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_STREAM
        )

        self.server_sock.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_REUSEADDR,
            1
        )

        self.server_sock.bind(
            ("0.0.0.0", self.data_port)
        )

        self.server_sock.listen(1)

        try:

            self.start_remote_stream()

            self.wait_connection()

            self.receive_loop()

        finally:

            self.cleanup()

            self.signals.finished.emit()

            self.save_data()

    def save_data(self):

        if len(self.all_data) == 0:
            print("No data to save")
            return

        data = np.concatenate(self.all_data)

        filename = os.path.join(
            self.save_path,
            f"trigger_{datetime.now().strftime('%Y%m%d_%H%M%S')}.npz"
        )

        os.makedirs(self.save_path, exist_ok=True)

        np.savez_compressed(filename, msts=np.array(data))

        print(f"Saved {len(data)} samples to {filename}")

    def stop(self):
        self._is_running = False

# ---------- Главное окно ----------
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.ip = 'rp-f05e99.local'
        self.path = r'Interface'
        self.threadpool = QThreadPool()
        self.trigger_worker = None
        self.continuous_worker = None
        self.initUI()

    def initUI(self):
        # ---------- Поля ----------
        self.path_label = QLabel("Save to folder:")
        self.path_input = QLineEdit()
        self.path_input.setFixedSize(110, 25)
        self.path_input.setText(self.path)
        self.browse_button = QPushButton("Browse...")
        self.browse_button.setFixedSize(100, 35)
        self.browse_button.clicked.connect(self.browse_folder)

        self.ip_label = QLabel("RP IP:")
        self.ip_input = QLineEdit()
        self.ip_input.setFixedSize(110, 25)
        self.ip_input.setText(self.ip)
        self.ip_input.setPlaceholderText("192.168.1.100")
        self.ip_input.textChanged.connect(self.on_ip_changed)


        # Поля для Continuous mode (они же видны всегда, но Trigger mode их игнорирует)
        self.int_label = QLabel("Decimation:")
        self.int_input = QSpinBox()
        self.int_input.setFixedSize(60, 25)
        self.int_input.setRange(0, 100000)
        self.int_input.setValue(256)

        self.trig_label = QLabel("Trigger:")
        self.trig_input = QLineEdit()
        self.trig_input.setFixedSize(70, 25)
        self.trig_input.setText("CHB_PE")


        # Кнопки
        self.start_trigger_button = QPushButton('Trigger mode (TCP)')
        self.start_trigger_button.setFixedSize(130, 35)
        self.start_trigger_button.clicked.connect(self.start_trigger_worker)

        self.start_continuous_button = QPushButton('Continuous mode')
        self.start_continuous_button.setFixedSize(130, 35)
        self.start_continuous_button.clicked.connect(self.start_continuous_worker)

        self.stop_workers_button = QPushButton('Stop')
        self.stop_workers_button.setFixedSize(100, 35)
        self.stop_workers_button.clicked.connect(self.stop_workers)

        # Графики
        self.plot_widget_ch1 = pg.PlotWidget()
        self.plot_widget_ch1.setTitle('CH1')
        self.plot_widget_ch1.showGrid(x=True, y=True)
        self.plot1 = self.plot_widget_ch1.plot(pen=pg.mkPen(color='b', width=1), name='CH1')
        self.plot_widget_ch2 = pg.PlotWidget()
        self.plot_widget_ch2.setTitle('CH2')
        self.plot_widget_ch2.showGrid(x=True, y=True)
        self.plot2 = self.plot_widget_ch2.plot(pen=pg.mkPen(color='r', width=1), name='CH2')
        self.plot_widget_ch1.setXLink(self.plot_widget_ch2)


        # Layout
        main_layout = QHBoxLayout()
        left_layout = QVBoxLayout()
        left_layout.addWidget(self.ip_label)
        left_layout.addWidget(self.ip_input)
        left_layout.addWidget(self.int_label)
        left_layout.addWidget(self.int_input)
        left_layout.addWidget(self.trig_label)
        left_layout.addWidget(self.trig_input)
        left_layout.addWidget(self.start_continuous_button)
        left_layout.addWidget(self.start_trigger_button)
        left_layout.addWidget(self.path_label)
        left_layout.addWidget(self.path_input)
        left_layout.addWidget(self.browse_button)
        left_layout.addWidget(self.stop_workers_button)

        right_layout = QVBoxLayout()
        right_layout.addWidget(self.plot_widget_ch1)
        right_layout.addWidget(self.plot_widget_ch2)

        main_layout.addLayout(left_layout)
        main_layout.addLayout(right_layout)
        self.setLayout(main_layout)
        self.setGeometry(300, 300, 950, 600)
        self.setWindowTitle('Accelerometer controller')

    # Служебные методы
    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose directory", "")
        if folder:
            self.path_input.setText(folder)

    def on_ip_changed(self, text):
        self.ip = text


    def start_trigger_worker(self):
        self.stop_workers()
        # Используем только необходимые параметры: IP RP, порт, путь к скрипту, учётные данные SSH
        self.trigger_worker = TriggerWorker(
            rp_ip=self.ip_input.text().strip(),
            save_path=self.path_input.text()
        )
        self.trigger_worker.signals.finished.connect(self.trigger_worker_finished)
        self.trigger_worker.signals.data.connect(self.update_plot_trigger)
        self.threadpool.start(self.trigger_worker)

    def start_continuous_worker(self):
        self.stop_workers()
        if self.continuous_worker is None:
            ip = self.ip_input.text()
            dec = self.int_input.value()
            self.continuous_worker = ContinuousWorker(ip=ip, dec=dec)
            self.continuous_worker.signals.finished.connect(self.continuous_worker_finished)
            self.continuous_worker.signals.data.connect(self.update_plot_continuous)
            self.threadpool.start(self.continuous_worker)

    def stop_workers(self):
        if self.trigger_worker is not None:
            print("Stopping trigger mode")
            self.trigger_worker.stop()
        if self.continuous_worker is not None:
            print("Stopping continuous mode")
            self.continuous_worker.stop()

    def trigger_worker_finished(self):
        self.trigger_worker = None

    def continuous_worker_finished(self):
        self.continuous_worker = None

    @pyqtSlot(np.ndarray)
    def update_plot_trigger(self, ch1_proc):
        self.plot1.setData(ch1_proc)
        self.plot2.clear()

    @pyqtSlot(np.ndarray)
    def update_plot_continuous(self, data):
        if data.dtype == np.int16:
            proc = (data.astype(np.float32) + 168) / 8191.0 * 20
        else:
            proc = data
        self.plot1.setData(proc)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())