from PyQt5.QtCore import QRunnable, QThreadPool, pyqtSlot, QObject, pyqtSignal
from PyQt5.QtWidgets import QApplication, QWidget, QPushButton, QVBoxLayout, QLineEdit, QLabel, QSpinBox, QDoubleSpinBox, QHBoxLayout, QFileDialog


from datetime import datetime
import sys
import time
import random
import os

import numpy as np
import redpitaya_scpi as scpi
import pyqtgraph as pg
pg.setConfigOption('background', 'w')  # Белый фон
pg.setConfigOption('foreground', 'k')  # Чёрные линии и текст

N = 16384

def read_single_char(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read(1)


def write_char(file_path, char):
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(char)


# непрерывный режим
class Worker2Signals(QObject):
    finished = pyqtSignal()
    data = pyqtSignal(np.ndarray)  # Добавляем сигнал с данными

class Worker2(QRunnable):
    def __init__(self, ip, dec):
        super().__init__()
        self.ip = ip
        self.dec = dec
        self.signals = Worker2Signals()
        self._is_running = True

    @pyqtSlot()
    def run(self):
        print("Continious mode was started")

        IP = self.ip
        dec = self.dec
        data_units = 'volts'
        data_format = 'ascii'
        rp = scpi.scpi(IP)

        rp.tx_txt('ACQ:RST')

        rp.tx_txt(f"ACQ:DEC:Factor {dec}")
        rp.tx_txt(f"ACQ:DATA:Units {data_units.upper()}")
        rp.tx_txt(f"ACQ:DATA:FORMAT {data_format.upper()}")
        rp.tx_txt('ACQ:SOUR1:GAIN HV')
        rp.tx_txt('ACQ:SOUR2:GAIN HV')

        i = 0
        while self._is_running:



            rp.tx_txt('ACQ:START')
            rp.tx_txt('ACQ:TRig NOW')

            while 1:
                rp.tx_txt('ACQ:TRig:STAT?')
                if rp.rx_txt() == 'TD':
                    break

            rp.tx_txt('ACQ:SOUR1:DATA?')
            buff_string = rp.rx_txt()
            rp.tx_txt('ACQ:STOP')
            buff_string = buff_string.strip('{}\n\r').replace("  ", "").split(',')
            buff = np.array(buff_string).astype(np.float64)

            self.signals.data.emit(buff)
            print(i)
            i += 1
            time.sleep(0)

        rp.tx_txt('ACQ:RST')
        print("continious mode was stopped")
        self.signals.finished.emit()

    def stop(self):
        self._is_running = False

# trigger mode acquisition
class WorkerSignals(QObject):
    finished = pyqtSignal()
    data = pyqtSignal(tuple)  # Добавляем сигнал с данными

class Worker(QRunnable):
    def __init__(self, ip, dec, tl, path, ttime, delay):
        super().__init__()
        self.ip = ip
        self.ttime = ttime
        self.delay = delay
        self.dec = dec
        self. tl = tl
        self.path = path
        self.signals = WorkerSignals()
        self._is_running = True

        # self.fname = ''

    @pyqtSlot()
    def run(self):

        print("trigger mode was started")

        IP = self.ip
        dec = self.dec
        ttime = self.ttime
        ttime = ttime*1e-3
        trig_lvl = self.tl
        path = self.path
        delay = self.delay

        data_units = 'RAW'
        data_format = 'BIN'
        acq_trig = 'CH2_PE'

        rp = scpi.scpi(IP)

        # rp.tx_txt('ACQ:RST')

        # rp.tx_txt(f"ACQ:DEC:Factor {dec}")
        # rp.tx_txt(f"ACQ:DATA:Units {data_units.upper()}")
        # rp.tx_txt(f"ACQ:DATA:FORMAT {data_format.upper()}")
        # rp.tx_txt(f"ACQ:TRig:LEV {trig_lvl}")
        #rp.tx_txt('ACQ:TRig:DLY 0')
        # rp.tx_txt('ACQ:SOUR1:GAIN HV')
        # rp.tx_txt('ACQ:SOUR2:GAIN HV')



        #rp.tx_txt(f"ACQ:TRig {acq_trig}")

        write_char("%s/scan_state.txt" % path, '0')
        
        rp.tx_txt('ACQ:RST')

        rp.tx_txt(f"ACQ:DEC:Factor {dec}")
        rp.tx_txt(f"ACQ:DATA:Units {data_units.upper()}")
        rp.tx_txt(f"ACQ:DATA:FORMAT {data_format.upper()}")
        rp.tx_txt(f"ACQ:TRig:LEV {trig_lvl}")
        rp.tx_txt(f'ACQ:TRig:DLY {delay}')
        rp.tx_txt('ACQ:SOUR1:GAIN HV')
        rp.tx_txt('ACQ:SOUR2:GAIN HV')


        buff_array = []
        buff_array1 = []
        while self._is_running:
            check_stat = read_single_char("%s/scan_state.txt" % path)
            i = 0
            while self._is_running and check_stat == '1':

                rp.tx_txt('ACQ:START')
                rp.tx_txt(f"ACQ:TRig {acq_trig}")

                check_stat = read_single_char("%s/scan_state.txt" % path) # может не нужен

                st = time.time()
                while self._is_running and check_stat == '1':
                    rp.tx_txt('ACQ:TRig:STAT?')
                    if rp.rx_txt() == 'TD':
                        break  
                    check_stat = read_single_char("%s/scan_state.txt" % path)
                    #time.sleep(0)

                # if i>0:    
                #     ft = time.time()
                #     print('time',(ft-st)*1e3)
                # st = time.time() 

                #end_time = time.time()
                #print((end_time-start_time)*1e3, "acq time")
                #start_time = time.time()

                #time.sleep(0)
                if not self._is_running or check_stat == '0':
                    rp.tx_txt('ACQ:START')
                    rp.tx_txt(f"ACQ:TRig {acq_trig}")
                    break

                rp.tx_txt('ACQ:SOUR1:DATA?')
                buff_bin1 = rp.rx_arb()
                rp.tx_txt('ACQ:SOUR2:DATA?')
                buff_bin2 = rp.rx_arb()

                #rp.tx_txt('ACQ:STOP') # возможно стоит убрать ввиду бессмысленности
                #rp.tx_txt("ACQ:RST:CH2") # вроде как не нужно
                #buff_string = buff_string.strip('{}\n\r').replace("  ", "").split(',')
                #buff = np.array(buff_string).astype(np.float64)
                buff_int1 = np.frombuffer(buff_bin1, dtype='>i2')
                buff_int2 = np.frombuffer(buff_bin2, dtype='>i2')
                #buff_float = (buff_int.astype(np.float16)+168)  / 8191.0*20

                #buff[1] = buff[1]
                check_stat = read_single_char("%s/scan_state.txt" % path) # может не нужен
                if check_stat == '1':
                    #print(np.mean(buff_int1))
                    buff_array.append(buff_int1) #np.save(f'{path}/{name}/{i}.npy', buff_int1)
                    buff_array1.append(buff_int2)

                self.signals.data.emit((buff_int1, buff_int2))  # Эмитируем tuple для обоих каналов
                i +=1
                #check_stat = read_single_char("%s/scan_state.txt" % path) # возможно это теперь можно убрать
                #time.sleep(0)  # чтобы не грузить CPU

            #print(len(buff_array))
            if len(buff_array) != 0:
                name = datetime.now()
                name = name.strftime("%d%m%y%H%M%S")
                ran_pref = f"{random.randint(0, 99):02d}"
                ln = f"{len(buff_array)}"
                name = ran_pref+name+ln
                #print("here")
                print(len(buff_array))
                #buff_array = np(buff_array)
                #buff_array1 = np(buff_array1)
                np.save(f'{path}/{name}.npy', buff_array)
                np.save(f'{path}/{name}trig.npy', buff_array1)
                buff_array = []
                buff_array1 = []

            #time.sleep(0)

        rp.tx_txt('ACQ:RST')
        print("Flow was finished")
        self.signals.finished.emit()

    def stop(self):
        print("Flow stop")
        self._is_running = False


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        # self.ip = 'rp-f05e99.local'
        self.ip = '192.168.54.171'
        # self.path = 'C:/Users/MakarovAO/Desktop/Adamov_Kirill/gravity_measurements/gravity measure vib/testdata'
        self.path = r'C:/Users/MakarovAO/Desktop/Adamov_Kirill/gravity_measurements/gravity_measure_vib/testdata'#'C:\Users\KapustaDN\PycharmProjects\quantum_sensors_lab\gravimeter gui'
        self.threadpool = QThreadPool()
        self.worker = None
        self.worker2 = None
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

    def browse_folder(self):
        # Открываем диалог выбора папки
        folder = QFileDialog.getExistingDirectory(self, "Choose directory", "")
        if folder:
            self.path_input.setText(folder)  # Записываем выбранный путь в QLineEdit


    def on_ip_changed(self, text):
        self.ip = text
        print("IP changed on:", self.ip)

    def start_worker(self):
        self.stop_workers()
        if self.worker is None:
            ip = self.ip_input.text()
            dec = self.int_input.value()
            ttime = self.ttime_input.value()
            tl = self.trig_input.value()
            path = self.path_input.text()
            delay = self.delay_input.value()
            self.worker = Worker(ip=ip, dec=dec, tl=tl, path=path, ttime=ttime, delay=delay)
            self.worker.signals.finished.connect(self.worker_finished)
            self.worker.signals.data.connect(self.update_plot)  # Подписываемся на данные
            self.threadpool.start(self.worker)
        else:
            print("The flow have been already started")

    def start_worker2(self):
        self.stop_workers()
        if self.worker2 is None:
            ip = self.ip_input.text()
            dec = self.int_input.value()
            self.worker2 = Worker2(ip=ip,dec=dec)
            self.worker2.signals.finished.connect(self.worker2_finished)
            self.worker2.signals.data.connect(self.update_plot)
            self.threadpool.start(self.worker2)
        else:
            print("Continious mode has already been started ")

    def stop_workers(self):
        if self.worker is not None:
            print("Stopping trigger mode")
            self.worker.stop()
        if self.worker2 is not None:
            print("Stopping continious mode")
            self.worker2.stop()
        if self.worker is None and self.worker2 is None:
            print("Both modes disabled")

    def worker_finished(self):
        print("Trigger finished execution")
        self.worker = None

    def worker2_finished(self):
        print("Continious acquistion finished execution")
        self.worker2 = None

    @pyqtSlot(object)
    def update_plot(self, data):
        ttime = self.ttime_input.value()
        time_axis = np.linspace(0, ttime, N)
        if isinstance(data, tuple) and len(data) == 2:
            # Trigger mode: два канала
            ch1, ch2 = data
            ch1_proc = (ch1.astype(np.float32) + 168) / 8191.0 * 20
            ch2_proc = (ch2.astype(np.float32) + 168) / 8191.0 * 20
            self.plot1.setData(ch1_proc)
            self.plot2.setData(ch2_proc)
        elif isinstance(data, np.ndarray):
            # Continuous mode: только CH1
            if data.dtype == np.int16:
                proc = (data.astype(np.float32) + 168) / 8191.0 * 20
            else:
                proc = data
            self.plot1.setData(proc)
            # CH2 очищаем (не рисуем)
        else:
            print("Unknown data type received")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())