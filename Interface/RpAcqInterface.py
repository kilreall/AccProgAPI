from PyQt5.QtCore import QRunnable, QThreadPool, pyqtSlot, QObject, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication, QWidget, QPushButton, QVBoxLayout, QLineEdit,
    QLabel, QSpinBox, QDoubleSpinBox, QHBoxLayout, QFileDialog,
    QComboBox
)
from PyQt5.QtWidgets import QDialog, QMessageBox
from datetime import datetime
import sys, os, socket, paramiko
import numpy as np
import time
import shlex
import pyqtgraph as pg
pg.setConfigOption('background', 'w')
pg.setConfigOption('foreground', 'k')

N = 16384


class UploadDialog(QDialog):
    uploaded = pyqtSignal(str)   # remote_path при успехе

    def __init__(self, rp_ip, ssh_user="root", ssh_pass="root",
                 remote_dir="/root", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Upload script to Red Pitaya")
        self.setModal(True)
        self.rp_ip      = rp_ip
        self.ssh_user   = ssh_user
        self.ssh_pass   = ssh_pass
        self.remote_dir = remote_dir
        self.remote_path = None
        self.upload_worker = None
        self._build_ui()

    def _build_ui(self):
        self.local_label  = QLabel("Local script:")
        self.local_input  = QLineEdit()
        self.local_input.setPlaceholderText("C:/path/to/stream.py")
        self.browse_btn   = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self._browse)

        file_row = QHBoxLayout()
        file_row.addWidget(self.local_input)
        file_row.addWidget(self.browse_btn)

        self.remote_label = QLabel(f"Destination: {self.remote_dir}/<filename>")
        self.status       = QLabel("")
        self.status.setWordWrap(True)

        self.upload_btn = QPushButton("Upload")
        self.upload_btn.clicked.connect(self._upload)
        self.close_btn  = QPushButton("Close")
        self.close_btn.clicked.connect(self.reject)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(self.upload_btn)
        btn_row.addWidget(self.close_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self.local_label)
        layout.addLayout(file_row)
        layout.addWidget(self.remote_label)
        layout.addWidget(self.status)
        layout.addLayout(btn_row)

        self.resize(430, 190)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose script", "",
            "Python files (*.py);;All files (*)")
        if not path:
            return
        self.local_input.setText(path)
        name = os.path.basename(path)
        if name:
            self.remote_path = f"{self.remote_dir}/{name}"
            self.remote_label.setText(f"Destination: {self.remote_path}")

    def _upload(self):
        local = self.local_input.text().strip()
        if not local or not os.path.isfile(local):
            self.status.setText("Файл не найден")
            return
        name = os.path.basename(local)
        if not name:
            self.status.setText("Некорректное имя файла")
            return
        if self.upload_worker is not None:
            return

        self.remote_path = f"{self.remote_dir}/{name}"
        self.upload_btn.setEnabled(False)
        self.browse_btn.setEnabled(False)
        self.close_btn.setEnabled(False)
        self.status.setText("Загрузка…")

        self.upload_worker = UploadWorker(
            rp_ip       = self.rp_ip,
            ssh_user    = self.ssh_user,
            ssh_pass    = self.ssh_pass,
            local_path  = local,
            remote_path = self.remote_path,
        )
        self.upload_worker.signals.status.connect(self.status.setText)
        self.upload_worker.signals.error.connect(self._on_error)
        self.upload_worker.signals.success.connect(self._on_success)
        self.upload_worker.signals.finished.connect(self._on_finished)
        QThreadPool.globalInstance().start(self.upload_worker)

    def _on_error(self, msg):
        self.status.setText(f"Ошибка: {msg}")

    def _on_success(self, remote_path):
        name = os.path.basename(remote_path)
        self.uploaded.emit(name)
        self.status.setText(f"✓ Загружено: {remote_path}")
        self.status.setStyleSheet("color: #060;")

    def _on_finished(self):
        self.upload_btn.setEnabled(True)
        self.browse_btn.setEnabled(True)
        self.close_btn.setEnabled(True)
        self.upload_worker = None


class UploadWorkerSignals(QObject):
    finished = pyqtSignal()
    error    = pyqtSignal(str)   # текст ошибки
    status   = pyqtSignal(str)   # прогресс («Connecting…», «Uploading…»)
    success  = pyqtSignal(str)   # ⬅ remote_path при успехе

class UploadWorker(QRunnable):
    """Копирует локальный скрипт на Red Pitaya по SFTP и делает его исполняемым."""

    def __init__(self, rp_ip, ssh_user, ssh_pass, local_path,
                 remote_path="/root/stream.py"):
        super().__init__()
        self.rp_ip       = rp_ip
        self.ssh_user    = ssh_user
        self.ssh_pass    = ssh_pass
        self.local_path  = local_path
        self.remote_path = remote_path
        self.signals     = UploadWorkerSignals()

    @pyqtSlot()
    def run(self):
        client = None
        try:
            # 1) Проверка локального файла (до SSH — чтобы не тратить соединение)
            if not os.path.isfile(self.local_path):
                self.signals.error.emit(
                    f"Локальный файл не найден: {self.local_path}")
                return
            if not os.path.isfile(self.local_path) or os.path.getsize(self.local_path) == 0:
                self.signals.error.emit("Локальный файл пуст")
                return

            # 2) SSH-сессия
            self.signals.status.emit(f"Подключение к {self.rp_ip}…")
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(self.rp_ip,
                           username=self.ssh_user,
                           password=self.ssh_pass,
                           timeout=10)

            # 3) SFTP-копирование
            self.signals.status.emit(
                f"Загрузка {os.path.basename(self.local_path)} → {self.remote_path}…")
            sftp = client.open_sftp()
            try:
                sftp.put(self.local_path, self.remote_path)
            finally:
                sftp.close()

            # 4) chmod +x с проверкой кода возврата
            self.signals.status.emit("chmod +x…")
            cmd = f"chmod +x {shlex.quote(self.remote_path)}"
            _, stdout, stderr = client.exec_command(cmd)
            exit_status = stdout.channel.recv_exit_status()   # ⬅ важно!
            if exit_status != 0:
                err = stderr.read().decode(errors="replace").strip()
                self.signals.error.emit(
                    f"chmod завершился с кодом {exit_status}: {err}")
                return

            self.signals.status.emit(f"Готово: {self.remote_path}")
            self.signals.success.emit(self.remote_path)
        except Exception as e:
            self.signals.error.emit(f"{type(e).__name__}: {e}")
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
            self.signals.finished.emit()



class TriggerWorkerSignals(QObject):
    finished = pyqtSignal()
    data = pyqtSignal(object)

class TriggerWorker(QRunnable):
    def __init__(self, rp_ip, pc_ip, save_path, dec, trig_src, trig_lvl, trig_dly, mode_ch1, mode_ch2, ch, remote_script="/root/stream.py"):
        super().__init__()
        self.rp_ip = rp_ip
        self.pc_ip = pc_ip
        self.dec = dec
        self.mode_ch1 = mode_ch1      # ⬅ отдельно для CH1
        self.mode_ch2 = mode_ch2      # ⬅ отдельно для CH2
        self.ch = ch
        self.remote_script=remote_script
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

            # --- прибить всё, что могло остаться от прошлых сессий ---
            kill_cmd = f"pkill -f {shlex.quote(self.remote_script)} || true"
            _, kout, _ = self.client.exec_command(kill_cmd)
            kout.channel.recv_exit_status()      # дождаться завершения pkill
            time.sleep(0.3)                      # дать ОС отпустить регистры/сокеты

            # --- запуск нового экземпляра ---
            cmd = (
                "PYTHONPATH=/opt/redpitaya/lib/python:$PYTHONPATH "
                f"/usr/bin/python3 {shlex.quote(self.remote_script)} "
                f"--pc-ip {self.pc_ip} "
                f"--trig-lvl {self.trig_lvl} "
                f"--trig-dly {self.trig_dly} "
                f"--trig-src {self.trig_src} "
                f"--dec {self.dec} "
                f"--mode-ch1 {self.mode_ch1} "
                f"--mode-ch2 {self.mode_ch2} "
                f"--channels {self.ch} "
            )
            self.stdin, self.stdout, self.stderr = \
                self.client.exec_command(cmd)

            # --- проверка, что скрипт реально стартовал (не упал на импорте/аргументах) ---
            time.sleep(0.5)
            check_cmd = f"pgrep -f {shlex.quote(self.remote_script)}"
            _, cout, _ = self.client.exec_command(check_cmd)
            status = cout.channel.recv_exit_status()
            if status != 0:
                try:
                    err = self.stderr.read().decode(errors="replace")
                except Exception:
                    err = "<no stderr>"
                print(f"[RP] stream.py failed to start:\n{err}")
                raise RuntimeError("Remote stream failed to start")

            print("Remote stream started.")

    def wait_connection(self):
        print("Waiting for RedPitaya...")
        self.server_sock.settimeout(1.0)
        while self._is_running:
            try:
                self.conn, addr = self.server_sock.accept()
                self.conn.settimeout(1.0)
                print(f"Connected from {addr}")
                return
            except socket.timeout:
                continue
            except OSError:
                # сокет закрыт stop() — выходим, run() увидит self.conn is None
                return
        

    def receive_loop(self):
        pb = N * 2
        if self.ch == "CH1+CH2":
            pb = pb * 2

        # ⬅ вольт на полную шкалу — зависит от режима каждого канала
        SCALE_V = {"HV": 20.0, "LV": 1.0}
        scale1 = SCALE_V[self.mode_ch1]
        scale2 = SCALE_V[self.mode_ch2]

        buffer = bytearray()

        while self._is_running:
            try:
                data = self.conn.recv(65536)
            except socket.timeout:
                continue
            except OSError as e:
                # сюда попадаем, когда stop() закрыл сокет под нами —
                # это штатный сценарий остановки, не ошибка
                if self._is_running:
                    print(f"[TriggerWorker] recv error: {e}")
                break
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

                    self.temp_file.write(ch1.tobytes())
                    self.temp_file.write(ch2.tobytes())

                    self.samples_count += N

                    # ⬅ разные масштабы для разных режимов
                    # ch1 = (ch1.astype(np.float32) + offset1) / 8191 * scale1
                    # ch2 = (ch2.astype(np.float32) + offset2) / 8191 * scale2

                    ch1 = ch1.astype(np.float32) / 8191 * scale1
                    ch2 = ch2.astype(np.float32) / 8191 * scale2

                    self.signals.data.emit((ch1, ch2))

                else:

                    self.temp_file.write(
                        packet.tobytes()
                    )

                    self.samples_count += len(packet)

                    # ⬅ масштаб зависит от того, какой канал выбран
                    proc = (packet.astype(np.float32)) / 8191 * scale_single

                    self.signals.data.emit(proc)

    def cleanup(self):

        if self.conn:
            self.conn.close()

        if self.server_sock:
            self.server_sock.close()

        if self.client:
            self.client.close()

    @pyqtSlot()
    def run(self):
        try:
            self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                self.server_sock.bind(("0.0.0.0", self.data_port))
            except OSError as e:
                print(f"[TriggerWorker] bind failed: {e}")
                return
            self.server_sock.listen(1)

            self.start_remote_stream()
            self.wait_connection()
            if self.conn is None:          # ⬅ Stop до коннекта — выходим штатно
                return

            self.temp_file = open("trigger_stream.tmp", "wb")
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

        # разбудить accept()
        if self.server_sock:
            try:
                self.server_sock.close()
            except OSError:
                pass

        # закрыть активное соединение (если есть)
        if self.conn:
            try:
                self.conn.close()
            except OSError:
                pass

# ---------- Главное окно ----------
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.ip = 'rp-f0fdf8.local'
        self.IP = "192.168.55.224"
        self.path = r'Interface'
        self.remote_dir = r"/root" 
        self.threadpool = QThreadPool()
        self.trigger_worker = None
        self._pending_start = False 
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


        # --- Настройка адресов ---
        self.ip_label = QLabel("RP IP:")
        self.ip_input = QLineEdit()
        self.ip_input.setFixedSize(110, 25)
        self.ip_input.setText(self.ip)
        self.ip_input.setPlaceholderText("rp-f0fdf8.local")
        self.ip_input.textChanged.connect(self.on_ip_changed)

        self.IP_label = QLabel("PC IP:")
        self.IP_input = QLineEdit()
        self.IP_input.setFixedSize(110, 25)
        self.IP_input.setText(self.IP)
        self.IP_input.setPlaceholderText("192.168.5.224")
        self.IP_input.textChanged.connect(self.on_IP_changed)

        # --- Настройка redpitaya ---
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

        self.mode_ch1_label = QLabel("Mode CH1:")
        self.mode_ch1_input = QComboBox()
        self.mode_ch1_input.setFixedSize(60, 25)
        self.mode_ch1_input.addItems(["LV", "HV"])
        self.mode_ch1_input.setCurrentText("LV")

        self.mode_ch2_label = QLabel("Mode CH2:")
        self.mode_ch2_input = QComboBox()
        self.mode_ch2_input.setFixedSize(60, 25)
        self.mode_ch2_input.addItems(["LV", "HV"])
        self.mode_ch2_input.setCurrentText("HV")

        self.ch_label = QLabel("Channels:")
        self.ch_input = QComboBox()
        self.ch_input.addItems([
            "CH1",
            "CH2",
            "CH1+CH2"
        ])
        self.ch_input.setCurrentText("CH1+CH2")

        self.trig_lvl_label = QLabel("Trigger level:")
        self.trig_lvl = QDoubleSpinBox()
        self.trig_lvl.setFixedSize(60, 25)
        self.trig_lvl.setRange(-20, 20)
        self.trig_lvl.setValue(2.0)

        self.trig_dly_label = QLabel("Trigger delay:")
        self.trig_dly = QSpinBox()
        self.trig_dly.setFixedSize(60, 25)
        self.trig_dly.setRange(-8192, 100000)
        self.trig_dly.setValue(-6800)


 
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

        # --- top-right: имя скрипта + мини-кнопка ---
        self.script_name_input = QLineEdit()
        self.script_name_input.setFixedSize(160, 25)
        self.script_name_input.setText("stream.py")          # ⬅ реальный текст, а не placeholder
        self.script_name_input.setPlaceholderText("stream.py")  # остаётся подсказкой, если пользователь всё сотрёт
        self.script_name_input.setToolTip(
            "Имя скрипта в /root на Red Pitaya (запускается по Start)")

        self.script_button = QPushButton("⚙")
        self.script_button.setFixedSize(32, 25)
        self.script_button.setToolTip("Upload script to Red Pitaya")
        self.script_button.clicked.connect(self.open_upload_dialog)

        top_layout = QHBoxLayout()
        top_layout.addStretch()
        top_layout.addWidget(QLabel("Script:"))
        top_layout.addWidget(self.script_name_input)               # ⬅ QLineEdit
        top_layout.addWidget(self.script_button)


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
        left_layout.addWidget(self.mode_ch1_label)
        left_layout.addWidget(self.mode_ch1_input)
        left_layout.addWidget(self.mode_ch2_label)
        left_layout.addWidget(self.mode_ch2_input)
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
        outer_layout = QVBoxLayout()
        outer_layout.addLayout(top_layout)
        outer_layout.addLayout(main_layout)
        self.setLayout(outer_layout)
        self.setGeometry(300, 300, 950, 600)
        self.setWindowTitle('Redpitaya controller')

        

    # Служебные методы

    def open_upload_dialog(self):
        dlg = UploadDialog(
            rp_ip      = self.ip_input.text().strip(),
            ssh_user   = "root",
            ssh_pass   = "root",
            remote_dir = self.remote_dir,
            parent     = self,
        )
        dlg.uploaded.connect(self.on_script_uploaded)
        dlg.exec_()

    def on_script_uploaded(self, name):
        # ⬅ заполняем поле тем, что реально залили — пользователь может изменить
        self.script_name_input.setText(name)

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose directory", "")
        if folder:
            self.path_input.setText(folder)

    def on_ip_changed(self, text):
        self.ip = text

    def on_IP_changed(self, text):
        self.IP = text

    def start_trigger_worker(self):
        # ⬅ сброс счётчика кадров — каждый Start начинается с Frame 1
        self.frame_counter = 0
        self.last_frame_time = None

        # если старый воркер ещё жив — просим остановиться и запоминаем намерение
        if self.trigger_worker is not None:
            self._pending_start = True
            self.stop_workers()
            return

        self._launch_trigger_worker()

    def _launch_trigger_worker(self):
        name = self.script_name_input.text().strip()

        if not name:
            QMessageBox.warning(
                self, "No script",
                "Укажите имя скрипта в поле Script (например, stream.py)")
            return
        if "/" in name or name in (".", ".."):
            QMessageBox.warning(
                self, "Invalid name",
                "Имя не должно содержать '/' и не может быть '.' или '..'")
            return

        remote_script = f"{self.remote_dir}/{name}"

        worker = TriggerWorker(
            rp_ip         = self.ip_input.text().strip(),
            pc_ip         = self.IP_input.text().strip(),
            save_path     = self.path_input.text(),
            dec           = int(self.dec_input.currentText()),
            trig_src      = self.trig_input.currentText(),
            trig_lvl      = self.trig_lvl.value(),
            trig_dly      = self.trig_dly.value(),
            mode_ch1      = self.mode_ch1_input.currentText(),
            mode_ch2      = self.mode_ch2_input.currentText(),
            ch            = self.ch_input.currentText(),
            remote_script = remote_script,
        )
        # ⬅ лямбда захватывает ИМЕННО этот воркер — чтобы finished от старого
        # не обнулил ссылку на новый
        worker.signals.finished.connect(
            lambda w=worker: self._on_worker_finished(w))
        worker.signals.data.connect(self.update_plot_trigger)

        self.trigger_worker = worker
        self.threadpool.start(worker)

    def stop_workers(self):
        if self.trigger_worker is not None:
            print("Stopping ...")
            self.trigger_worker.stop()

    def _on_worker_finished(self, worker):
        # обнуляем ссылку, только если она всё ещё указывает на этого воркера
        if self.trigger_worker is worker:
            self.trigger_worker = None

        # если пользователь нажал Start, пока старый умирал — запускаем сейчас
        if self._pending_start:
            self._pending_start = False
            self._launch_trigger_worker()


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