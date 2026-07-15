#!/usr/bin/env python3
"""Unified PyQt5 GUI for the Red Pitaya acquisition setup.

Combines what used to be two separate PC-side programs:

- the SSH manager (start/stop/status/log tail of ``rp_collector.py`` on the board), and
- the TCP receiver (``pc_receiver.py``) that accepts the streamed int16 packets and
  saves them to a timestamped ``.npz``.

On top of that it shows the incoming signal live: a waveform view and an FFT
spectrum view (pyqtgraph). Runs on the PC.
"""

import os
import shlex
import socket
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import paramiko
import pyqtgraph as pg
from PyQt5.QtCore import Qt, QObject, QRunnable, QThread, QThreadPool, QTimer, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

DECIMATIONS = (1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536)
TRIGGER_SOURCES = ("NOW", "CHA_PE", "CHA_NE", "CHB_PE", "CHB_NE")
MAX_LOG_LINES = 5000
SSH_TIMEOUT = 10.0
RP_BASE_RATE = 125_000_000.0  # Red Pitaya base sampling rate, Hz
PLOT_INTERVAL_MS = 66  # ~15 fps redraw of the live plots


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


# --- SSH plumbing (unchanged from rp_ssh_manager.py) ------------------------


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


# --- TCP receiver (formerly pc_receiver.py), now a Qt worker ----------------


class ReceiverWorker(QThread):
    """TCP server that reassembles fixed-size int16 packets from the collector.

    Runs the same accept/recv loop pc_receiver.py used, but lives inside the GUI:
    it accumulates every packet for later saving, keeps the most recent one for
    live plotting, and reports progress via signals.
    """

    packet_received = pyqtSignal(int)  # emits the running packet count
    status = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, host, port, samples, recv_buffer=65536, parent=None):
        super().__init__(parent)
        self.host = host
        self.port = port
        self.samples = samples
        self.recv_buffer = recv_buffer
        self._stop_requested = False
        self._lock = threading.Lock()
        self._all_data = []
        self._latest = None

    def stop(self):
        self._stop_requested = True

    def latest_packet(self):
        with self._lock:
            return self._latest

    def snapshot(self):
        """Return a copy of everything received so far, for saving."""
        with self._lock:
            return list(self._all_data)

    def packet_count(self):
        with self._lock:
            return len(self._all_data)

    def clear(self):
        with self._lock:
            self._all_data.clear()
            self._latest = None

    def run(self):
        packet_bytes = self.samples * 2  # int16
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1.0)
        try:
            sock.bind((self.host, self.port))
            sock.listen(1)
        except OSError as exc:
            self.error.emit(f"Cannot listen on {self.host}:{self.port} ({exc})")
            sock.close()
            return

        self.status.emit(f"listening on {self.host}:{self.port}")

        try:
            while not self._stop_requested:
                try:
                    conn, addr = sock.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break

                self.status.emit(f"connected: {addr[0]}:{addr[1]}")
                buffer = bytearray()
                with conn:
                    conn.settimeout(1.0)
                    while not self._stop_requested:
                        try:
                            data = conn.recv(self.recv_buffer)
                        except socket.timeout:
                            continue
                        except OSError:
                            break

                        if not data:
                            self.status.emit("peer closed connection")
                            break

                        buffer.extend(data)
                        while len(buffer) >= packet_bytes:
                            chunk = bytes(buffer[:packet_bytes])
                            del buffer[:packet_bytes]
                            packet = np.frombuffer(chunk, dtype=np.int16).copy()
                            with self._lock:
                                self._all_data.append(packet)
                                self._latest = packet
                                count = len(self._all_data)
                            self.packet_received.emit(count)
                if not self._stop_requested:
                    self.status.emit(f"listening on {self.host}:{self.port}")
        finally:
            sock.close()
            self.status.emit("receiver stopped")


# --- Main window ------------------------------------------------------------


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.threadpool = QThreadPool()
        self.threadpool.setMaxThreadCount(4)
        self.log_tail_worker = None
        self.receiver_worker = None
        self._packet_count = 0
        self.init_ui()

        # Redraw the plots on a timer so plotting rate is decoupled from the
        # (potentially bursty) packet arrival rate.
        self.plot_timer = QTimer(self)
        self.plot_timer.setInterval(PLOT_INTERVAL_MS)
        self.plot_timer.timeout.connect(self.update_plots)

    def init_ui(self):
        self.setWindowTitle("Red Pitaya Manager")
        self.setGeometry(200, 200, 1180, 760)

        left_panel = self._build_left_panel()
        right_panel = self._build_right_panel()

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([420, 760])

        main_layout = QHBoxLayout()
        main_layout.addWidget(splitter)
        self.setLayout(main_layout)

    def _build_left_panel(self):
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

        # --- Receiver group ---
        self.listen_host_input = QLineEdit("0.0.0.0")
        self.out_dir_input = QLineEdit(".")
        self.browse_button = QPushButton("Browse…")
        self.browse_button.clicked.connect(self.on_browse_out_dir)
        self.recv_buffer_input = QSpinBox()
        self.recv_buffer_input.setRange(1024, 1_048_576)
        self.recv_buffer_input.setValue(65536)
        self.autosave_checkbox = QCheckBox("Auto-save on stop")
        self.autosave_checkbox.setChecked(True)

        out_dir_row = QHBoxLayout()
        out_dir_row.addWidget(self.out_dir_input)
        out_dir_row.addWidget(self.browse_button)

        recv_form = QFormLayout()
        recv_form.addRow("Listen host:", self.listen_host_input)
        recv_form.addRow("Output dir:", out_dir_row)
        recv_form.addRow("Recv buffer (bytes):", self.recv_buffer_input)
        recv_form.addRow("", self.autosave_checkbox)
        recv_note = QLabel("Listen port and packet size (N) are taken from the collector parameters above.")
        recv_note.setWordWrap(True)
        recv_note.setStyleSheet("color: gray; font-size: 11px;")
        recv_form.addRow(recv_note)
        recv_group = QGroupBox("Receiver (built-in)")
        recv_group.setLayout(recv_form)

        inner = QVBoxLayout()
        inner.addWidget(ssh_group)
        inner.addWidget(paths_group)
        inner.addWidget(params_group)
        inner.addWidget(recv_group)
        inner.addStretch(1)

        inner_widget = QWidget()
        inner_widget.setLayout(inner)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner_widget)
        scroll.setMinimumWidth(400)
        return scroll

    def _build_right_panel(self):
        # --- Collector (SSH) actions ---
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

        collector_actions = QHBoxLayout()
        for btn in (self.test_button, self.start_button, self.stop_button, self.refresh_button, self.tail_button):
            collector_actions.addWidget(btn)

        self.status_label = QLabel("Collector: unknown")
        self.status_label.setStyleSheet("font-weight: bold;")

        # --- Receiver actions ---
        self.recv_button = QPushButton("Start receiver")
        self.recv_button.clicked.connect(self.on_toggle_receiver)
        self.save_button = QPushButton("Save now")
        self.save_button.clicked.connect(self.on_save_now)
        self.clear_button = QPushButton("Clear buffer")
        self.clear_button.clicked.connect(self.on_clear_buffer)

        receiver_actions = QHBoxLayout()
        for btn in (self.recv_button, self.save_button, self.clear_button):
            receiver_actions.addWidget(btn)
        receiver_actions.addStretch(1)

        self.receiver_label = QLabel("Receiver: idle — 0 packets")
        self.receiver_label.setStyleSheet("font-weight: bold;")

        # --- Plots ---
        pg.setConfigOptions(antialias=True)
        self.waveform_plot = pg.PlotWidget()
        self.waveform_plot.setLabel("bottom", "Sample")
        self.waveform_plot.setLabel("left", "Amplitude", units="raw int16")
        self.waveform_plot.showGrid(x=True, y=True, alpha=0.3)
        self.waveform_plot.setDownsampling(auto=True)
        self.waveform_plot.setClipToView(True)
        self.waveform_curve = self.waveform_plot.plot(pen=pg.mkPen("#2b8cbe", width=1))

        self.spectrum_plot = pg.PlotWidget()
        self.spectrum_plot.setLabel("bottom", "Frequency", units="Hz")
        self.spectrum_plot.setLabel("left", "Magnitude")
        self.spectrum_plot.showGrid(x=True, y=True, alpha=0.3)
        self.spectrum_curve = self.spectrum_plot.plot(pen=pg.mkPen("#e6550d", width=1))

        plot_tabs = QTabWidget()
        plot_tabs.addTab(self.waveform_plot, "Waveform")
        plot_tabs.addTab(self.spectrum_plot, "Spectrum (FFT)")

        # --- Log ---
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFontFamily("monospace")

        log_container = QWidget()
        log_layout = QVBoxLayout()
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.addWidget(QLabel("Remote log:"))
        log_layout.addWidget(self.log_view)
        log_container.setLayout(log_layout)

        view_splitter = QSplitter(Qt.Vertical)
        view_splitter.addWidget(plot_tabs)
        view_splitter.addWidget(log_container)
        view_splitter.setStretchFactor(0, 3)
        view_splitter.setStretchFactor(1, 1)
        view_splitter.setSizes([500, 220])

        right_layout = QVBoxLayout()
        right_layout.addWidget(QLabel("Collector (on the board, over SSH):"))
        right_layout.addLayout(collector_actions)
        right_layout.addWidget(self.status_label)
        right_layout.addWidget(QLabel("Receiver (on this PC):"))
        right_layout.addLayout(receiver_actions)
        right_layout.addWidget(self.receiver_label)
        right_layout.addWidget(view_splitter, 1)

        right_widget = QWidget()
        right_widget.setLayout(right_layout)
        return right_widget

    # --- config helpers ---

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

    def set_collector_actions_enabled(self, enabled):
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

        self.set_collector_actions_enabled(False)
        self.status_label.setText(f"Collector: {label}...")
        task = SSHTask(conn, command)
        task.signals.finished.connect(lambda text: self._on_task_finished(on_success, text))
        task.signals.error.connect(self._on_task_error)
        self.threadpool.start(task)

    def _on_task_finished(self, on_success, text):
        self.set_collector_actions_enabled(True)
        on_success(text)

    def _on_task_error(self, message):
        self.set_collector_actions_enabled(True)
        self.status_label.setText("Collector: error")
        QMessageBox.critical(self, "SSH error", message)

    # --- collector actions ---

    def on_test_connection(self):
        self.run_ssh_task("echo OK", lambda text: self.status_label.setText(f"Collector: connection OK ({text})"), "testing connection")

    def on_start_collector(self):
        conn = self.current_connection_config()
        params = self.current_collector_params()
        if not params.pc_host:
            QMessageBox.warning(self, "Invalid input", "PC receiver host is required")
            return
        command = build_start_command(conn, params)

        def handle(text):
            if text == "NOSTART" or not text:
                self.status_label.setText("Collector: failed to start")
                QMessageBox.critical(self, "Start failed", "Collector did not write a PID file. Check the remote log.")
            else:
                self.status_label.setText(f"Collector: running (pid {text})")

        self.run_ssh_task(command, handle, "starting collector")

    def on_stop_collector(self):
        self.run_ssh_task(build_stop_command(self.current_connection_config()), lambda _text: self.status_label.setText("Collector: stopped"), "stopping collector")

    def on_refresh_status(self):
        def handle(text):
            if text.startswith("RUNNING"):
                pid = text.split()[1]
                self.status_label.setText(f"Collector: running (pid {pid})")
            else:
                self.status_label.setText("Collector: stopped")

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

    # --- receiver actions ---

    def on_browse_out_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select output directory", self.out_dir_input.text() or ".")
        if path:
            self.out_dir_input.setText(path)

    def on_toggle_receiver(self):
        if self.receiver_worker is not None:
            self.receiver_worker.stop()
            self.receiver_worker.wait(3000)
            if self.autosave_checkbox.isChecked():
                self.save_data(prompt=False)
            self.receiver_worker = None
            self.plot_timer.stop()
            self.recv_button.setText("Start receiver")
            self.receiver_label.setText(f"Receiver: stopped — {self._packet_count} packets")
            return

        host = self.listen_host_input.text().strip() or "0.0.0.0"
        port = self.pc_port_input.value()
        samples = self.samples_input.value()
        recv_buffer = self.recv_buffer_input.value()

        self._packet_count = 0
        self.receiver_worker = ReceiverWorker(host, port, samples, recv_buffer)
        self.receiver_worker.packet_received.connect(self.on_packet_received)
        self.receiver_worker.status.connect(self.on_receiver_status)
        self.receiver_worker.error.connect(self.on_receiver_error)
        self.receiver_worker.start()
        self.plot_timer.start()
        self.recv_button.setText("Stop receiver")
        self.receiver_label.setText("Receiver: starting…")

    def on_packet_received(self, count):
        self._packet_count = count

    def on_receiver_status(self, text):
        self.receiver_label.setText(f"Receiver: {text} — {self._packet_count} packets")

    def on_receiver_error(self, message):
        QMessageBox.critical(self, "Receiver error", message)
        if self.receiver_worker is not None:
            self.receiver_worker.wait(1000)
        self.receiver_worker = None
        self.plot_timer.stop()
        self.recv_button.setText("Start receiver")
        self.receiver_label.setText("Receiver: error")

    def on_save_now(self):
        self.save_data(prompt=True)

    def on_clear_buffer(self):
        if self.receiver_worker is not None:
            self.receiver_worker.clear()
        self._packet_count = 0
        self.waveform_curve.clear()
        self.spectrum_curve.clear()
        self.receiver_label.setText("Receiver: buffer cleared — 0 packets")

    def save_data(self, prompt):
        if self.receiver_worker is None:
            if prompt:
                QMessageBox.information(self, "Nothing to save", "The receiver is not running.")
            return
        data = self.receiver_worker.snapshot()
        if not data:
            if prompt:
                QMessageBox.information(self, "Nothing to save", "No packets have been received yet.")
            return

        out_dir = self.out_dir_input.text().strip() or "."
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(self, "Save failed", f"Cannot create output directory:\n{exc}")
            return

        name = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(out_dir, f"data_{name}.npz")
        try:
            np.savez_compressed(path, msts=np.array(data))
        except OSError as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return

        self.append_log(f"[receiver] saved {len(data)} packets to {path}")
        if prompt:
            QMessageBox.information(self, "Saved", f"Saved {len(data)} packets to\n{path}")

    # --- plotting ---

    def update_plots(self):
        if self.receiver_worker is None:
            return
        packet = self.receiver_worker.latest_packet()
        if packet is None:
            return

        y = packet.astype(np.float64)
        n = y.size
        self.waveform_curve.setData(np.arange(n), y)

        # Spectrum of the latest packet. Effective sample rate follows the
        # collector's decimation factor.
        decimation = int(self.decimation_input.currentText())
        fs = RP_BASE_RATE / decimation
        if n >= 2:
            window = np.hanning(n)
            spectrum = np.abs(np.fft.rfft(y * window)) / n
            freqs = np.fft.rfftfreq(n, d=1.0 / fs)
            self.spectrum_curve.setData(freqs, spectrum)

    def closeEvent(self, event):
        if self.log_tail_worker is not None:
            self.log_tail_worker.stop()
            self.log_tail_worker.wait(2000)
        if self.receiver_worker is not None:
            self.receiver_worker.stop()
            self.receiver_worker.wait(3000)
            if self.autosave_checkbox.isChecked():
                self.save_data(prompt=False)
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
