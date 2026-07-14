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
    def __init__(self, rp_ip, data_port, script_path, ssh_user, ssh_pass, save_path):
        super().__init__()
        self.rp_ip = rp_ip
        self.data_port = data_port
        self.script_path = script_path
        self.ssh_user = ssh_user
        self.ssh_pass = ssh_pass
        self.save_path = save_path
        self.signals = TriggerWorkerSignals()
        self._is_running = True
        self.all_data = []

    @pyqtSlot()
    def run(self):
        print("Trigger mode (SSH) started")

        # 1. Создаём TCP-сервер на заданном порту
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.settimeout(10.0)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server_sock.bind(('0.0.0.0', self.data_port))
            server_sock.listen(1)
            print(f"Server listening on port {self.data_port}")
        except OSError as e:
            print(f"Bind error: {e}")
            self.signals.finished.emit()
            return

        conn = None
        buffer = bytearray()
        try:
            # 2. Запускаем скрипт на RP по SSH (без аргументов)
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(self.rp_ip, username=self.ssh_user, password=self.ssh_pass, timeout=5)

            cmd = f"python3 {self.script_path}"
            print(f"Executing on RP: {cmd}")
            ssh.exec_command(cmd, get_pty=False)  # скрипт запущен, дальше он работает сам
            time.sleep(1)  # даём время на инициализацию и подключение

            # 3. Принимаем соединение от RP
            try:
                conn, addr = server_sock.accept()
                print(f"Connected from {addr}")
                server_sock.settimeout(1.0)
                while self._is_running:
                    try:
                        data = conn.recv(65536)
                    except socket.timeout:
                        continue
                    if not data:
                        print("Connection closed")
                        break
                    buffer.extend(data)
                    while len(buffer) >= PACKET_BYTES:
                        packet_bytes = buffer[:PACKET_BYTES]
                        buffer = buffer[PACKET_BYTES:]
                        packet = np.frombuffer(packet_bytes, dtype=np.int16)
                        self.all_data.append(packet.copy())
                        ch1_proc = (packet.astype(np.float32) + 168) / 8191.0 * 20
                        self.signals.data.emit(ch1_proc)
            except socket.timeout:
                print("Timeout waiting for RP connection. Check IP, port and firewall.")
        except Exception as e:
            print(f"SSH error: {e}")
        finally:
            server_sock.close()
            if conn:
                conn.close()
            if self.all_data:
                try:
                    name = datetime.now().strftime("%d%m%y%H%M%S")
                    ran_pref = f"{random.randint(0, 99):02d}"
                    ln = f"{len(self.all_data)}"
                    filename = f"{self.save_path}/{ran_pref}{name}{ln}.npy"
                    np.save(filename, np.array(self.all_data))
                    print(f"Saved {len(self.all_data)} packets to {filename}")
                except Exception as e:
                    print(f"Save error: {e}")
            print("Trigger mode finished")
            self.signals.finished.emit()

    def stop(self):
        self._is_running = False

# ---------- Главное окно ----------
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.ip = 'rp-f05e99.local'
        self.path = r'C:/temp'
        self.script_path = '/root/stream.py'
        self.threadpool = QThreadPool()
        self.trigger_worker = None
        self.continuous_worker = None
        self.ssh_client = None
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

        self.connect_button = QPushButton("Connect")
        self.connect_button.setFixedSize(100, 35)
        self.connect_button.clicked.connect(self.connect_to_rp)
        self.connection_status = QLabel("Not connected")
        self.connection_status.setStyleSheet("color: red;")

        self.ssh_user_label = QLabel("SSH user:")
        self.ssh_user_input = QLineEdit("root")
        self.ssh_user_input.setFixedSize(80, 25)
        self.ssh_pass_label = QLabel("SSH pass:")
        self.ssh_pass_input = QLineEdit("root")
        self.ssh_pass_input.setFixedSize(80, 25)
        self.ssh_pass_input.setEchoMode(QLineEdit.Password)

        self.port_label = QLabel("Data port:")
        self.port_input = QSpinBox()
        self.port_input.setFixedSize(70, 25)
        self.port_input.setRange(1024, 65535)
        self.port_input.setValue(5000)

        self.script_label = QLabel("Script on RP:")
        self.script_path_input = QLineEdit(self.script_path)
        self.script_path_input.setFixedSize(140, 25)

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

        self.ttime_label = QLabel("Acq time (ms):")
        self.ttime_input = QDoubleSpinBox()
        self.ttime_input.setFixedSize(60, 25)
        self.ttime_input.setRange(0, 1000)
        self.ttime_input.setDecimals(3)
        self.ttime_input.setValue(33.556)

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
        self.plot_widget_ch1.setXRange(0., self.ttime_input.value())

        # Layout
        main_layout = QHBoxLayout()
        left_layout = QVBoxLayout()
        left_layout.addWidget(self.ip_label)
        left_layout.addWidget(self.ip_input)
        left_layout.addWidget(self.connect_button)
        left_layout.addWidget(self.connection_status)
        left_layout.addWidget(self.ssh_user_label)
        left_layout.addWidget(self.ssh_user_input)
        left_layout.addWidget(self.ssh_pass_label)
        left_layout.addWidget(self.ssh_pass_input)
        left_layout.addWidget(self.port_label)
        left_layout.addWidget(self.port_input)
        left_layout.addWidget(self.script_label)
        left_layout.addWidget(self.script_path_input)
        left_layout.addWidget(self.int_label)
        left_layout.addWidget(self.int_input)
        left_layout.addWidget(self.trig_label)
        left_layout.addWidget(self.trig_input)
        left_layout.addWidget(self.start_continuous_button)
        left_layout.addWidget(self.start_trigger_button)
        left_layout.addWidget(self.ttime_label)
        left_layout.addWidget(self.ttime_input)
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
        self.connection_status.setText("Not connected")
        self.connection_status.setStyleSheet("color: red;")

    def connect_to_rp(self):
        ip = self.ip_input.text().strip()
        if not ip:
            return
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(ip, username='root', password='root', timeout=5)
            self.ssh_client = ssh
            self.connection_status.setText("Connected")
            self.connection_status.setStyleSheet("color: green;")
        except Exception as e:
            self.connection_status.setText("Connection failed")
            self.connection_status.setStyleSheet("color: red;")

    def start_trigger_worker(self):
        self.stop_workers()
        # Используем только необходимые параметры: IP RP, порт, путь к скрипту, учётные данные SSH
        self.trigger_worker = TriggerWorker(
            rp_ip=self.ip_input.text().strip(),
            data_port=self.port_input.value(),
            script_path=self.script_path_input.text().strip(),
            ssh_user=self.ssh_user_input.text().strip() or "root",
            ssh_pass=self.ssh_pass_input.text().strip() or "root",
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