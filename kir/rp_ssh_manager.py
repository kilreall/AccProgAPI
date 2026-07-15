#!/usr/bin/env python3
"""PyQt5 GUI for managing rp_collector.py on a Red Pitaya board over SSH.

Starts/stops the collector as a background process (nohup + PID file) and
streams its remote log file back into the window. Runs on the PC, next to
pc_receiver.py.
"""

import shlex
import socket
import sys
import time
from dataclasses import dataclass

import paramiko
from PyQt5.QtCore import QObject, QRunnable, QThread, QThreadPool, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

DECIMATIONS = (1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536)
TRIGGER_SOURCES = ("NOW", "CHA_PE", "CHA_NE", "CHB_PE", "CHB_NE")
MAX_LOG_LINES = 5000
SSH_TIMEOUT = 10.0


@dataclass(frozen=True)
class SSHConnectionConfig:
    host: str
    port: int
    username: str
    password: str
    remote_python: str
    remote_script: str
    pid_file: str
    log_file: str


@dataclass(frozen=True)
class CollectorParams:
    pc_host: str
    pc_port: int
    decimation: int
    trigger_src: str
    channel: int
    samples: int
    queue_size: int
    reconnect_delay: float


def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def build_start_command(conn, params):
    args = " ".join(
        [
            "--pc-host", shlex.quote(params.pc_host),
            "--pc-port", str(params.pc_port),
            "--decimation", str(params.decimation),
            "--trigger-src", shlex.quote(params.trigger_src),
            "--channel", str(params.channel),
            "--samples", str(params.samples),
            "--queue-size", str(params.queue_size),
            "--reconnect-delay", str(params.reconnect_delay),
            "--pid-file", shlex.quote(conn.pid_file),
        ]
    )
    script = shlex.quote(conn.remote_script)
    python = shlex.quote(conn.remote_python)
    log_file = shlex.quote(conn.log_file)
    return (
        f"nohup {python} {script} {args} >> {log_file} 2>&1 < /dev/null &\n"
        f"sleep 0.5\n"
        f"cat {shlex.quote(conn.pid_file)} 2>/dev/null || echo NOSTART"
    )


def build_stop_command(conn):
    pid_file = shlex.quote(conn.pid_file)
    return (
        f'pid=$(cat {pid_file} 2>/dev/null); '
        f'if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then '
        f'kill "$pid"; sleep 1; '
        f'kill -0 "$pid" 2>/dev/null && kill -9 "$pid"; '
        f'fi; rm -f {pid_file}; echo STOPPED'
    )


def build_status_command(conn):
    pid_file = shlex.quote(conn.pid_file)
    return (
        f'pid=$(cat {pid_file} 2>/dev/null); '
        f'if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then '
        f'echo "RUNNING $pid"; else echo STOPPED; fi'
    )


class SSHTaskSignals(QObject):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)


class SSHTask(QRunnable):
    """Opens its own short-lived SSH connection, runs one command, closes."""

    def __init__(self, conn, command):
        super().__init__()
        self.conn = conn
        self.command = command
        self.signals = SSHTaskSignals()

    @pyqtSlot()
    def run(self):
        client = None
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                hostname=self.conn.host,
                port=self.conn.port,
                username=self.conn.username,
                password=self.conn.password,
                timeout=SSH_TIMEOUT,
                banner_timeout=SSH_TIMEOUT,
                auth_timeout=SSH_TIMEOUT,
            )
            _stdin, stdout, stderr = client.exec_command(self.command, timeout=SSH_TIMEOUT)
            exit_status = stdout.channel.recv_exit_status()
            out_text = stdout.read().decode(errors="replace").strip()
            err_text = stderr.read().decode(errors="replace").strip()
            if exit_status != 0 and err_text:
                self.signals.error.emit(err_text)
            else:
                self.signals.finished.emit(out_text)
        except Exception as exc:
            self.signals.error.emit(str(exc))
        finally:
            if client is not None:
                client.close()


class LogTailWorker(QThread):
    """Persistent connection running `tail -f` on the remote log file."""

    line_received = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True

    def run(self):
        client = None
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                hostname=self.conn.host,
                port=self.conn.port,
                username=self.conn.username,
                password=self.conn.password,
                timeout=SSH_TIMEOUT,
                banner_timeout=SSH_TIMEOUT,
                auth_timeout=SSH_TIMEOUT,
            )
            command = f"touch {shlex.quote(self.conn.log_file)}; tail -n 200 -f {shlex.quote(self.conn.log_file)}"
            _stdin, stdout, _stderr = client.exec_command(command)
            channel = stdout.channel
            channel.settimeout(1.0)
            buffer = b""

            while not self._stop_requested:
                if channel.recv_ready():
                    chunk = channel.recv(4096)
                    if not chunk:
                        break
                    buffer += chunk
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        self.line_received.emit(line.decode(errors="replace"))
                elif channel.exit_status_ready():
                    break
                else:
                    time.sleep(0.2)

            channel.close()
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            if client is not None:
                client.close()


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.threadpool = QThreadPool()
        self.threadpool.setMaxThreadCount(4)
        self.log_tail_worker = None
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Red Pitaya SSH Manager")
        self.setGeometry(300, 300, 760, 640)

        # --- SSH connection group ---
        self.host_input = QLineEdit("192.168.54.171")
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(22)
        self.username_input = QLineEdit("root")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setText("root")

        ssh_form = QFormLayout()
        ssh_form.addRow("RP host/IP:", self.host_input)
        ssh_form.addRow("SSH port:", self.port_input)
        ssh_form.addRow("Username:", self.username_input)
        ssh_form.addRow("Password:", self.password_input)
        ssh_group = QGroupBox("SSH connection")
        ssh_group.setLayout(ssh_form)

        # --- Remote paths group ---
        self.remote_python_input = QLineEdit("python3")
        self.remote_script_input = QLineEdit("/root/rp_collector.py")
        self.pid_file_input = QLineEdit("/tmp/rp_collector.pid")
        self.log_file_input = QLineEdit("/tmp/rp_collector.log")

        paths_form = QFormLayout()
        paths_form.addRow("Remote python:", self.remote_python_input)
        paths_form.addRow("Remote script path:", self.remote_script_input)
        paths_form.addRow("PID file:", self.pid_file_input)
        paths_form.addRow("Log file:", self.log_file_input)
        paths_group = QGroupBox("Remote paths (script must already be deployed)")
        paths_group.setLayout(paths_form)

        # --- Collector params group ---
        self.pc_host_input = QLineEdit(get_local_ip())
        self.pc_port_input = QSpinBox()
        self.pc_port_input.setRange(1, 65535)
        self.pc_port_input.setValue(5000)
        self.decimation_input = QComboBox()
        self.decimation_input.addItems([str(d) for d in DECIMATIONS])
        self.decimation_input.setCurrentText("1024")
        self.trigger_input = QComboBox()
        self.trigger_input.addItems(TRIGGER_SOURCES)
        self.trigger_input.setCurrentText("CHB_PE")
        self.channel_input = QComboBox()
        self.channel_input.addItems(["1", "2"])
        self.samples_input = QSpinBox()
        self.samples_input.setRange(1, 1_000_000)
        self.samples_input.setValue(16384)
        self.queue_size_input = QSpinBox()
        self.queue_size_input.setRange(1, 10000)
        self.queue_size_input.setValue(50)
        self.reconnect_delay_input = QDoubleSpinBox()
        self.reconnect_delay_input.setRange(0.1, 60.0)
        self.reconnect_delay_input.setValue(2.0)

        params_form = QFormLayout()
        params_form.addRow("PC receiver host:", self.pc_host_input)
        params_form.addRow("PC receiver port:", self.pc_port_input)
        params_form.addRow("Decimation:", self.decimation_input)
        params_form.addRow("Trigger source:", self.trigger_input)
        params_form.addRow("Channel:", self.channel_input)
        params_form.addRow("Samples (N):", self.samples_input)
        params_form.addRow("Queue size:", self.queue_size_input)
        params_form.addRow("Reconnect delay (s):", self.reconnect_delay_input)
        params_group = QGroupBox("Collector parameters")
        params_group.setLayout(params_form)

        # --- Actions ---
        self.test_button = QPushButton("Test connection")
        self.test_button.clicked.connect(self.on_test_connection)
        self.start_button = QPushButton("Start collector")
        self.start_button.clicked.connect(self.on_start_collector)
        self.stop_button = QPushButton("Stop collector")
        self.stop_button.clicked.connect(self.on_stop_collector)
        self.refresh_button = QPushButton("Refresh status")
        self.refresh_button.clicked.connect(self.on_refresh_status)
        self.tail_button = QPushButton("Start log tail")
        self.tail_button.clicked.connect(self.on_toggle_log_tail)

        actions_layout = QHBoxLayout()
        for btn in (self.test_button, self.start_button, self.stop_button, self.refresh_button, self.tail_button):
            actions_layout.addWidget(btn)

        self.status_label = QLabel("Status: unknown")
        self.status_label.setStyleSheet("font-weight: bold;")

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFontFamily("monospace")

        left_layout = QVBoxLayout()
        left_layout.addWidget(ssh_group)
        left_layout.addWidget(paths_group)
        left_layout.addWidget(params_group)
        left_layout.addStretch(1)

        right_layout = QVBoxLayout()
        right_layout.addLayout(actions_layout)
        right_layout.addWidget(self.status_label)
        right_layout.addWidget(QLabel("Remote log:"))
        right_layout.addWidget(self.log_view)

        main_layout = QHBoxLayout()
        main_layout.addLayout(left_layout, 1)
        main_layout.addLayout(right_layout, 2)
        self.setLayout(main_layout)

    # --- helpers ---

    def current_connection_config(self):
        return SSHConnectionConfig(
            host=self.host_input.text().strip(),
            port=self.port_input.value(),
            username=self.username_input.text().strip(),
            password=self.password_input.text(),
            remote_python=self.remote_python_input.text().strip(),
            remote_script=self.remote_script_input.text().strip(),
            pid_file=self.pid_file_input.text().strip(),
            log_file=self.log_file_input.text().strip(),
        )

    def current_collector_params(self):
        return CollectorParams(
            pc_host=self.pc_host_input.text().strip(),
            pc_port=self.pc_port_input.value(),
            decimation=int(self.decimation_input.currentText()),
            trigger_src=self.trigger_input.currentText(),
            channel=int(self.channel_input.currentText()),
            samples=self.samples_input.value(),
            queue_size=self.queue_size_input.value(),
            reconnect_delay=self.reconnect_delay_input.value(),
        )

    def validate_connection(self, conn):
        if not conn.host:
            return "RP host/IP is required"
        if not conn.username:
            return "Username is required"
        if not conn.remote_script:
            return "Remote script path is required"
        return None

    def set_actions_enabled(self, enabled):
        for btn in (self.test_button, self.start_button, self.stop_button, self.refresh_button):
            btn.setEnabled(enabled)

    def append_log(self, text):
        self.log_view.append(text)
        doc = self.log_view.document()
        if doc.blockCount() > MAX_LOG_LINES:
            cursor = self.log_view.textCursor()
            cursor.movePosition(cursor.Start)
            cursor.movePosition(cursor.Down, cursor.KeepAnchor, doc.blockCount() - MAX_LOG_LINES)
            cursor.removeSelectedText()
        scrollbar = self.log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def run_ssh_task(self, command, on_success, label):
        conn = self.current_connection_config()
        error = self.validate_connection(conn)
        if error:
            QMessageBox.warning(self, "Invalid input", error)
            return

        self.set_actions_enabled(False)
        self.status_label.setText(f"Status: {label}...")
        task = SSHTask(conn, command)
        task.signals.finished.connect(lambda text: self._on_task_finished(on_success, text))
        task.signals.error.connect(self._on_task_error)
        self.threadpool.start(task)

    def _on_task_finished(self, on_success, text):
        self.set_actions_enabled(True)
        on_success(text)

    def _on_task_error(self, message):
        self.set_actions_enabled(True)
        self.status_label.setText("Status: error")
        QMessageBox.critical(self, "SSH error", message)

    # --- actions ---

    def on_test_connection(self):
        self.run_ssh_task("echo OK", lambda text: self.status_label.setText(f"Status: connection OK ({text})"), "testing connection")

    def on_start_collector(self):
        conn = self.current_connection_config()
        params = self.current_collector_params()
        if not params.pc_host:
            QMessageBox.warning(self, "Invalid input", "PC receiver host is required")
            return
        command = build_start_command(conn, params)

        def handle(text):
            if text == "NOSTART" or not text:
                self.status_label.setText("Status: failed to start")
                QMessageBox.critical(self, "Start failed", "Collector did not write a PID file. Check the remote log.")
            else:
                self.status_label.setText(f"Status: running (pid {text})")

        self.run_ssh_task(command, handle, "starting collector")

    def on_stop_collector(self):
        self.run_ssh_task(build_stop_command(self.current_connection_config()), lambda _text: self.status_label.setText("Status: stopped"), "stopping collector")

    def on_refresh_status(self):
        def handle(text):
            if text.startswith("RUNNING"):
                pid = text.split()[1]
                self.status_label.setText(f"Status: running (pid {pid})")
            else:
                self.status_label.setText("Status: stopped")

        self.run_ssh_task(build_status_command(self.current_connection_config()), handle, "checking status")

    def on_toggle_log_tail(self):
        if self.log_tail_worker is not None:
            self.log_tail_worker.stop()
            self.log_tail_worker.wait(2000)
            self.log_tail_worker = None
            self.tail_button.setText("Start log tail")
            return

        conn = self.current_connection_config()
        error = self.validate_connection(conn)
        if error:
            QMessageBox.warning(self, "Invalid input", error)
            return

        self.log_view.clear()
        self.log_tail_worker = LogTailWorker(conn)
        self.log_tail_worker.line_received.connect(self.append_log)
        self.log_tail_worker.error.connect(self._on_tail_error)
        self.log_tail_worker.start()
        self.tail_button.setText("Stop log tail")

    def _on_tail_error(self, message):
        self.append_log(f"[log tail error] {message}")
        self.tail_button.setText("Start log tail")
        self.log_tail_worker = None

    def closeEvent(self, event):
        if self.log_tail_worker is not None:
            self.log_tail_worker.stop()
            self.log_tail_worker.wait(2000)
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
