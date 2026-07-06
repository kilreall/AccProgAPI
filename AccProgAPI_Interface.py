from PyQt5.QtCore import QRunnable, QThreadPool, pyqtSlot, QObject, pyqtSignal
from PyQt5.QtWidgets import QApplication, QWidget, QPushButton, QVBoxLayout, QLineEdit, QLabel, QSpinBox, QDoubleSpinBox, QHBoxLayout, QFileDialog

from datetime import datetime
import sys
import time
import random
import os

import numpy as np
import pyqtgraph as pg
import paramiko


class RedPitayaSSH:

    def __init__(self, host, user="root", password="root"):
        self.host = host
        self.user = user
        self.password = password
        self.client = None

    def connect(self):

        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(
            paramiko.AutoAddPolicy()
        )

        self.client.connect(
            hostname=self.host,
            username=self.user,
            password=self.password
        )


class MainWindow(QWidget):

    def __init__(self):
        super().__init__()
        self.ip = 'rp-f05e99.local'
        #self.ip = '192.168.54.171'
        # self.path = 'C:/Users/MakarovAO/Desktop/Adamov_Kirill/gravity_measurements/gravity measure vib/testdata'
        self.path = r'C:/Users/MakarovAO/Desktop/Adamov_Kirill/gravity_measurements/gravity_measure_vib/testdata'#'C:\Users\KapustaDN\PycharmProjects\quantum_sensors_lab\gravimeter gui'
        self.threadpool = QThreadPool()
        self.triggerMode = None
        self.continiousMode = None
        self.initUI()


    def initUI(self):

        # file path
        self.path_label = QLabel("path to folder:")
        self.path_input = QLineEdit()
        self.path_input.setFixedSize(110, 25) 
        self.path_input.setText(self.path)
        self.browse_button = QPushButton("Browse...")
        self.browse_button.setFixedSize(100, 35)
        self.browse_button.clicked.connect(self.browse_folder)


        # IP window
        self.ip_label = QLabel("Enter IP:")
        self.ip_input = QLineEdit(self)
        self.ip_input.setFixedSize(110, 25) 
        self.ip_input.setText(self.ip)
        self.ip_input.setPlaceholderText("For example, 192.168.1.100")
        self.ip_input.textChanged.connect(self.on_ip_changed)

        # decimation window
        self.int_label = QLabel("Enter dec:")
        self.int_input = QSpinBox()
        self.int_input.setFixedSize(60, 25)
        self.int_input.setRange(0, 100000)
        self.int_input.setValue(256) 

        # trig_lvl window
        self.trig_label = QLabel("Enter trig_lvl:")
        self.trig_input = QDoubleSpinBox()
        self.trig_input.setFixedSize(60, 25)
        self.trig_input.setRange(0, 10)
        self.trig_input.setValue(1.25)

        #trig_delay window
        self.delay_label = QLabel("Enter trig_delay:")
        self.delay_input = QSpinBox()
        self.delay_input.setFixedSize(60, 25)
        self.delay_input.setRange(-16000, 16000)
        self.delay_input.setValue(8100)

        # time acq window
        self.ttime_label = QLabel("Enter acq time: ms")
        self.ttime_input = QDoubleSpinBox()
        self.ttime_input.setFixedSize(60, 25)
        self.ttime_input.setRange(0, 1000)
        self.ttime_input.setDecimals(3) 
        self.ttime_input.setValue(33.556) 


        # Main window
        self.setGeometry(300, 300, 900, 600)
        self.setWindowTitle('Accelerometer controller')

        self.start_button = QPushButton('Trigger mode', self)
        self.start_button.setFixedSize(100, 35)
        self.start_button.clicked.connect(self.start_worker)

        self.start_worker2_button = QPushButton('Continious mode', self)
        self.start_worker2_button.setFixedSize(100, 35)
        self.start_worker2_button.clicked.connect(self.start_worker2)

        self.stop_workers_button = QPushButton('Stop', self)
        self.stop_workers_button.setFixedSize(100, 35)
        self.stop_workers_button.clicked.connect(self.stop_workers)

        # Создаём два отдельных PlotWidget для CH1 и CH2 с независимыми шкалами y
        self.plot_widget_ch1 = pg.PlotWidget()
        self.plot_widget_ch1.setTitle('CH1')
        self.plot_widget_ch1.showGrid(x=True, y=True)
        self.plot_widget_ch1.addLegend()
        self.plot1 = self.plot_widget_ch1.plot(pen=pg.mkPen(color='b', width=1), name='CH1')

        self.plot_widget_ch2 = pg.PlotWidget()
        self.plot_widget_ch2.setTitle('CH2')
        self.plot_widget_ch2.showGrid(x=True, y=True)
        self.plot_widget_ch2.addLegend()
        self.plot2 = self.plot_widget_ch2.plot(pen=pg.mkPen(color='r', width=1), name='CH2')

        # Синхронизируем шкалы x для обоих графиков (опционально, чтобы легко сравнивать)
        self.plot_widget_ch1.setXLink(self.plot_widget_ch2)  # CH1 х-ось связана с CH2
        self.plot_widget_ch1.setXRange(0., self.ttime_input.value())

        # Создаём главный горизонтальный layout
        main_layout = QHBoxLayout()

        # Левая вертикальная колонка с кнопками и полями ввода
        left_layout = QVBoxLayout()
        left_layout.addWidget(self.ip_label)
        left_layout.addWidget(self.ip_input)
        left_layout.addWidget(self.int_label)
        left_layout.addWidget(self.int_input)
        left_layout.addWidget(self.start_worker2_button)
        left_layout.addWidget(self.start_button)
        left_layout.addWidget(self.trig_label)
        left_layout.addWidget(self.trig_input)
        left_layout.addWidget(self.delay_label)
        left_layout.addWidget(self.delay_input)
        left_layout.addWidget(self.ttime_label)
        left_layout.addWidget(self.ttime_input)
        left_layout.addWidget(self.path_label)
        left_layout.addWidget(self.path_input)
        left_layout.addWidget(self.browse_button)
        left_layout.addWidget(self.stop_workers_button)

        # Правая колонка с рисунком
        right_layout = QVBoxLayout()
        right_layout.addWidget(self.plot_widget_ch1)
        right_layout.addWidget(self.plot_widget_ch2)  # Добавляем оба виджета стеком (вертикально)

        # Добавляем левую и правую части в главный горизонтальный layout
        main_layout.addLayout(left_layout)
        main_layout.addLayout(right_layout)

        # Устанавливаем главный layout на окно или виджет
        self.setLayout(main_layout)




if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())



