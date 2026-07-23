from PyQt5.QtCore import QRunnable, QThreadPool, pyqtSlot, QObject, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication, QWidget, QPushButton, QVBoxLayout, QLineEdit,
    QLabel, QSpinBox, QDoubleSpinBox, QHBoxLayout, QFileDialog,
    QComboBox
)
from datetime import datetime
import sys, os, socket, paramiko
import numpy as np
import time
import pyqtgraph as pg
pg.setConfigOption('background', 'w')
pg.setConfigOption('foreground', 'k')

N = 16384


class TriggerWorkerSignals(QObject):
    finished = pyqtSignal()
    data = pyqtSignal(object)

class TriggerWorker(QRunnable):
    def __init__(self, rp_ip, pc_ip, save_path, dec, trig_src, trig_lvl, trig_dly, mode, ch):
        super().__init__()
        self.rp_ip = rp_ip
        self.pc_ip = pc_ip
        self.dec = dec
        self.mode = mode
        self.ch = ch
        self.trig_src = trig_src
        self.trig_lvl = trig_lvl
        self.trig_dly = trig_dly
        self.data_port = 5000
        self.ssh_user = "root"
        self.ssh_pass = "root"
        self.save_path = save_path
        self.signals = TriggerWorkerSignals()
        self._is_running = True
        self.temp_file = None
        self.samples_count = 0
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

        #cmd = "PYTHONPATH=/opt/redpitaya/lib/python:$PYTHONPATH /usr/bin/python3 /root/stream.py"

        cmd = (
            "PYTHONPATH=/opt/redpitaya/lib/python:$PYTHONPATH "
            "/usr/bin/python3 /root/stream.py "
            f"--pc-ip {self.pc_ip} "
            f"--trig-lvl {self.trig_lvl} "
            f"--trig-dly {self.trig_dly} "
            f"--trig-src {self.trig_src} "
            f"--dec {self.dec} "
            f"--mode {self.mode} "
            f"--channels {self.ch} "
        )

        self.stdin, self.stdout, self.stderr = \
            self.client.exec_command(cmd)

        print("Remote stream started.")

    def wait_connection(self):

        print("Waiting for RedPitaya...")

        self.conn, addr = self.server_sock.accept()

        self.conn.settimeout(1.0)

        print(f"Connected from {addr}")
        

    def receive_loop(self):

        pb = N*2

        if self.ch =="CH1+CH2":
            pb = pb*2

        buffer = bytearray()

        while self._is_running:

            try:
                data = self.conn.recv(65536)

            except socket.timeout:
                continue

            if not data:
                break

            buffer.extend(data)

            while len(buffer) >= pb:

                packet = np.frombuffer(
                    buffer[:pb],
                    dtype=np.int16
                ).copy()

                buffer = buffer[pb:]


                if self.ch == "CH1+CH2":

                    ch1 = packet[:N]
                    ch2 = packet[N:N*2]


                    self.temp_file.write(
                        ch1.tobytes()
                    )

                    self.temp_file.write(
                        ch2.tobytes()
                    )


                    self.samples_count += N


                    ch1 = (
                        ch1.astype(np.float32)+168
                    )/8191*20


                    ch2 = (
                        ch2.astype(np.float32)+168
                    )/8191*20


                    self.signals.data.emit(
                        (ch1,ch2)
                    )


                else:


                    self.temp_file.write(
                        packet.tobytes()
                    )


                    self.samples_count += len(packet)


                    proc = (
                        packet.astype(np.float32)+168
                    )/8191*20


                    self.signals.data.emit(
                        proc
                    )

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
    
            self.temp_file = open(
                "trigger_stream.tmp",
                "wb"
            )

            self.receive_loop()

        finally:

            self.save_data()

            self.cleanup()

            self.signals.finished.emit()


    def save_data(self):

        if self.temp_file:
            self.temp_file.close()

        if self.samples_count == 0:
            print("No data received")
            return


        raw = np.fromfile(
            "trigger_stream.tmp",
            dtype=np.int16
        )


        filename = os.path.join(
            self.save_path,
            f"trigger_{datetime.now().strftime('%Y%m%d_%H%M%S')}.npz"
        )

        os.makedirs(
            self.save_path,
            exist_ok=True
        )


        if self.ch == "CH1+CH2":

            frames = raw.reshape(-1, 2, N)

            ch1 = frames[:,0,:]
            ch2 = frames[:,1,:]


            np.savez_compressed(
                filename,
                CH1=ch1,
                CH2=ch2,
                samples=ch1.size,
                timestamp=datetime.now().isoformat(),
                ip=self.rp_ip
            )


        else:

            data = raw.reshape(-1,N)

            np.savez_compressed(
                filename,
                data=data,
                samples=len(raw),
                timestamp=datetime.now().isoformat(),
                ip=self.rp_ip
            )


        os.remove("trigger_stream.tmp")

        print(
            f"Saved {len(raw)} samples -> {filename}"
        )

    def stop(self):
        self._is_running = False

# ---------- Главное окно ----------
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.ip = 'rp-f05e99.local'
        self.IP = "192.168.55.224"
        self.path = r'Interface'
        self.threadpool = QThreadPool()
        self.trigger_worker = None
        self.initUI()
        self.last_frame_time = None
        self.frame_counter = 0

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
        self.ip_input.setPlaceholderText("rp-f05e99.local")
        self.ip_input.textChanged.connect(self.on_ip_changed)

        self.IP_label = QLabel("PC IP:")
        self.IP_input = QLineEdit()
        self.IP_input.setFixedSize(110, 25)
        self.IP_input.setText(self.IP)
        self.IP_input.setPlaceholderText("192.168.5.224")
        self.IP_input.textChanged.connect(self.on_IP_changed)


        self.dec_label = QLabel("Decimation:")
        self.dec_input = QComboBox()
        self.dec_input.setFixedSize(60, 25)
        self.dec_input.addItems(["1","2","4","8","16","32","64","128","256","512","1024"])

        self.dec_input.setCurrentText("256")

        self.trig_label = QLabel("Trigger source:")
        self.trig_input = QComboBox()
        self.trig_input.addItems([
            "CHA_PE",
            "CHA_NE",
            "CHB_PE",
            "CHB_NE"
        ])
        self.trig_input.setCurrentText("CHB_PE")

        self.mode_label = QLabel("Mode:")
        self.mode_input = QComboBox()
        self.mode_input.addItems([
            "LV",
            "HV"
        ])
        self.mode_input.setCurrentText("HV")

        self.ch_label = QLabel("Channels:")
        self.ch_input = QComboBox()
        self.ch_input.addItems([
            "CH1",
            "CH2",
            "CH1+CH2"
        ])
        self.ch_input.setCurrentText("CH1")

        self.trig_lvl_label = QLabel("Trigger level:")
        self.trig_lvl = QDoubleSpinBox()
        self.trig_lvl.setFixedSize(60, 25)
        self.trig_lvl.setRange(-20, 20)
        self.trig_lvl.setValue(0.1)

        self.trig_dly_label = QLabel("Trigger delay:")
        self.trig_dly = QSpinBox()
        self.trig_dly.setFixedSize(60, 25)
        self.trig_dly.setRange(-8192, 100000)
        self.trig_dly.setValue(8192)


 
        # Кнопки
        self.start_trigger_button = QPushButton('Start')
        self.start_trigger_button.setFixedSize(130, 35)
        self.start_trigger_button.clicked.connect(self.start_trigger_worker)


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
        left_layout.addWidget(self.IP_label)
        left_layout.addWidget(self.IP_input)
        left_layout.addWidget(self.dec_label)
        left_layout.addWidget(self.dec_input)
        left_layout.addWidget(self.trig_label)
        left_layout.addWidget(self.trig_input)
        left_layout.addWidget(self.mode_label)
        left_layout.addWidget(self.mode_input)
        left_layout.addWidget(self.ch_label)
        left_layout.addWidget(self.ch_input)
        left_layout.addWidget(self.trig_lvl_label)
        left_layout.addWidget(self.trig_lvl)
        left_layout.addWidget(self.trig_dly_label)
        left_layout.addWidget(self.trig_dly)
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

    def on_IP_changed(self, text):
        self.IP = text


    def start_trigger_worker(self):
        self.stop_workers()
        # Используем только необходимые параметры: IP RP, порт, путь к скрипту, учётные данные SSH
        self.trigger_worker = TriggerWorker(
            rp_ip=self.ip_input.text().strip(),
            pc_ip=self.IP_input.text().strip(),
            save_path=self.path_input.text(),
            dec = int(self.dec_input.currentText()),
            trig_src=self.trig_input.currentText(),
            trig_lvl=self.trig_lvl.value(),
            trig_dly=self.trig_dly.value(),
            mode = self.mode_input.currentText(),
            ch = self.ch_input.currentText()
        )
        self.trigger_worker.signals.finished.connect(self.trigger_worker_finished)
        self.trigger_worker.signals.data.connect(self.update_plot_trigger)
        self.threadpool.start(self.trigger_worker)


    def stop_workers(self):
        if self.trigger_worker is not None:
            print("Stopping ...")
            self.trigger_worker.stop()


    def trigger_worker_finished(self):
        self.trigger_worker = None


    @pyqtSlot(object)
    def update_plot_trigger(self, data):

        now = time.perf_counter()

        if self.ch_input.currentText()=="CH1+CH2":


            ch1, ch2 = data


            self.plot1.setData(ch1)
            self.plot2.setData(ch2)

            if self.last_frame_time is not None:
                dt = (now - self.last_frame_time) * 1000  # мс

                print(
                    f"Frame {self.frame_counter}: "
                    f"{dt:.3f} ms  "
                )

            self.last_frame_time = now
            self.frame_counter += 1


        else:

            if self.last_frame_time is not None:
                dt = (now - self.last_frame_time) * 1000  # мс

                print(
                    f"Frame {self.frame_counter}: "
                    f"{dt:.3f} ms  "
                )

            self.last_frame_time = now
            self.frame_counter += 1

            if self.ch_input.currentText() == "CH1":

                self.plot1.setData(data)

            else:
                                
                self.plot2.setData(data)




if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())