import sys
import socket
import struct
import numpy as np
import time
import threading

from PyQt5.QtCore import (
    QThread, pyqtSignal, Qt, QTimer
)
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QGroupBox
)
import pyqtgraph as pg

N = 16384
DATA_PORT = 5000
HEADER_MAGIC = 0x52503031
HEADER_SIZE = 16

class ReceiverThread(QThread):
    """Поток приема данных"""
    
    data_signal = pyqtSignal(np.ndarray, np.ndarray)
    status_signal = pyqtSignal(str)
    count_signal = pyqtSignal(int)
    
    def __init__(self):
        super().__init__()
        self.running = False
        self.sock = None
        
    def run(self):
        """Основной цикл приема"""
        self.running = True
        self.status_signal.emit("Receiver started")
        
        try:
            # Создание сервера
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind(('0.0.0.0', DATA_PORT))
            self.sock.listen(1)
            self.sock.settimeout(1)
            
            self.status_signal.emit(f"Waiting on port {DATA_PORT}...")
            
            while self.running:
                try:
                    conn, addr = self.sock.accept()
                    self.status_signal.emit(f"Connected to {addr[0]}")
                    conn.settimeout(1)
                    
                    buffer = bytearray()
                    packet_count = 0
                    
                    while self.running:
                        try:
                            data = conn.recv(65536)
                            if not data:
                                break
                            
                            buffer.extend(data)
                            
                            # Обработка пакетов
                            while len(buffer) >= HEADER_SIZE:
                                header = buffer[:HEADER_SIZE]
                                magic, payload_size, packet_id, mode = struct.unpack(
                                    "<IIII", header
                                )
                                
                                if magic != HEADER_MAGIC:
                                    buffer.clear()
                                    break
                                
                                packet_size = HEADER_SIZE + payload_size
                                if len(buffer) < packet_size:
                                    break
                                
                                packet_data = buffer[HEADER_SIZE:packet_size]
                                buffer = buffer[packet_size:]
                                
                                # Конвертация данных
                                data_array = np.frombuffer(packet_data, dtype=np.int16)
                                ch1 = data_array[:N]
                                ch2 = data_array[N:]
                                
                                # Конвертация в вольты
                                ch1_v = (ch1.astype(np.float32) + 168) / 8191.0 * 20
                                ch2_v = (ch2.astype(np.float32) + 168) / 8191.0 * 20
                                
                                # Отправка сигнала
                                self.data_signal.emit(ch1_v, ch2_v)
                                
                                packet_count += 1
                                if packet_count % 10 == 0:
                                    self.count_signal.emit(packet_count)
                                    
                        except socket.timeout:
                            continue
                        except Exception as e:
                            self.status_signal.emit(f"Receive error: {e}")
                            break
                            
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        self.status_signal.emit(f"Accept error: {e}")
                        
        except Exception as e:
            self.status_signal.emit(f"Error: {e}")
        finally:
            self.cleanup()
            
    def cleanup(self):
        """Очистка"""
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None
        self.status_signal.emit("Receiver stopped")
        
    def stop(self):
        """Остановка"""
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except:
                pass

class MainWindow(QMainWindow):
    """Главное окно"""
    
    def __init__(self):
        super().__init__()
        self.receiver = None
        self.packet_count = 0
        
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle("RP Data Viewer")
        self.setGeometry(100, 100, 1000, 600)
        
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        # Панель управления
        control = QGroupBox("Control")
        control_layout = QHBoxLayout(control)
        
        self.ip_input = QLineEdit("192.168.55.171")
        self.ip_input.setFixedWidth(130)
        control_layout.addWidget(QLabel("RP IP:"))
        control_layout.addWidget(self.ip_input)
        
        self.start_btn = QPushButton("▶ Start Receiver")
        self.start_btn.clicked.connect(self.toggle_receiver)
        control_layout.addWidget(self.start_btn)
        
        control_layout.addStretch()
        
        self.status_label = QLabel("Ready")
        control_layout.addWidget(self.status_label)
        
        self.count_label = QLabel("Packets: 0")
        control_layout.addWidget(self.count_label)
        
        layout.addWidget(control)
        
        # Графики
        self.plot1 = pg.PlotWidget()
        self.plot1.setTitle("Channel 1")
        self.plot1.showGrid(x=True, y=True)
        self.plot1.setYRange(-20, 20)
        self.curve1 = self.plot1.plot(pen='b')
        layout.addWidget(self.plot1)
        
        self.plot2 = pg.PlotWidget()
        self.plot2.setTitle("Channel 2")
        self.plot2.showGrid(x=True, y=True)
        self.plot2.setYRange(-20, 20)
        self.curve2 = self.plot2.plot(pen='r')
        layout.addWidget(self.plot2)
        
    def toggle_receiver(self):
        """Запуск/остановка приемника"""
        if self.receiver and self.receiver.isRunning():
            self.stop_receiver()
        else:
            self.start_receiver()
            
    def start_receiver(self):
        """Запуск приемника"""
        self.receiver = ReceiverThread()
        self.receiver.data_signal.connect(self.update_plots)
        self.receiver.status_signal.connect(self.update_status)
        self.receiver.count_signal.connect(self.update_count)
        self.receiver.start()
        
        self.start_btn.setText("■ Stop")
        self.status_label.setText("Starting...")
        
    def stop_receiver(self):
        """Остановка приемника"""
        if self.receiver:
            self.receiver.stop()
            self.receiver.wait()
            self.receiver = None
            
        self.start_btn.setText("▶ Start Receiver")
        self.status_label.setText("Stopped")
        
    def update_plots(self, ch1, ch2):
        """Обновление графиков"""
        try:
            self.curve1.setData(ch1)
            self.curve2.setData(ch2)
        except Exception as e:
            print(f"Plot error: {e}")
            
    def update_status(self, msg):
        """Обновление статуса"""
        self.status_label.setText(msg)
        print(f"Status: {msg}")  # Вывод в консоль для отладки
        
    def update_count(self, count):
        """Обновление счетчика"""
        self.packet_count = count
        self.count_label.setText(f"Packets: {count}")
        
    def closeEvent(self, event):
        """Закрытие окна"""
        self.stop_receiver()
        event.accept()

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()