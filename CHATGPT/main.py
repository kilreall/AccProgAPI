import sys
import numpy as np


import receiver

from PyQt5.QtCore import *
from PyQt5.QtWidgets import *
import pyqtgraph as pg

pg.setConfigOption("background", "w")
pg.setConfigOption("foreground", "k")

N = 16384


class MainWindow(QWidget):

    def __init__(self):

        super().__init__()

        self.receiver = None
        self.ssh = None

        self.threadpool = QThreadPool()

        self.initUI()

    #####################################################################

    def initUI(self):

        self.setWindowTitle("Red Pitaya Controller")

        self.resize(1100,700)

        ###############################################################
        # SSH
        ###############################################################

        self.ipLabel = QLabel("RP IP")

        self.ipEdit = QLineEdit()
        self.ipEdit.setText("rp-f05e99.local")

        self.userLabel = QLabel("User")

        self.userEdit = QLineEdit()
        self.userEdit.setText("root")

        self.passLabel = QLabel("Password")

        self.passEdit = QLineEdit()
        self.passEdit.setEchoMode(QLineEdit.Password)
        self.passEdit.setText("root")

        ###############################################################
        # TCP
        ###############################################################

        self.portLabel = QLabel("TCP Port")

        self.portEdit = QSpinBox()

        self.portEdit.setRange(
            1000,
            65000
        )

        self.portEdit.setValue(
            5000
        )

        ###############################################################
        # Acquisition
        ###############################################################

        self.decLabel = QLabel(
            "Decimation"
        )

        self.decBox = QComboBox()

        self.decBox.addItems(
            [
                "1",
                "2",
                "4",
                "8",
                "16",
                "64",
                "1024",
                "8192",
                "65536"
            ]
        )

        self.decBox.setCurrentText(
            "1024"
        )

        ###############################################################

        self.triggerLabel = QLabel(
            "Trigger level"
        )

        self.triggerBox = QDoubleSpinBox()

        self.triggerBox.setDecimals(2)

        self.triggerBox.setRange(
            0,
            10
        )

        self.triggerBox.setValue(
            1.25
        )

        ###############################################################

        self.delayLabel = QLabel(
            "Trigger delay"
        )

        self.delayBox = QSpinBox()

        self.delayBox.setRange(
            -16384,
            16384
        )

        self.delayBox.setValue(
            8100
        )

        ###############################################################
        # Buttons
        ###############################################################

        self.connectButton = QPushButton(
            "Connect"
        )

        self.triggerButton = QPushButton(
            "Trigger mode"
        )

        self.contButton = QPushButton(
            "Continuous mode"
        )

        self.stopButton = QPushButton(
            "Stop"
        )

        ###############################################################
        # Plots
        ###############################################################

        self.plotCH1 = pg.PlotWidget()

        self.plotCH1.setTitle("CH1")

        self.plotCH1.showGrid(
            True,
            True
        )

        self.curve1 = self.plotCH1.plot(
            pen='b'
        )

        ###############################################################

        self.plotCH2 = pg.PlotWidget()

        self.plotCH2.setTitle("CH2")

        self.plotCH2.showGrid(
            True,
            True
        )

        self.curve2 = self.plotCH2.plot(
            pen='r'
        )

        self.plotCH1.setXLink(
            self.plotCH2
        )

        ###############################################################
        # Layout
        ###############################################################

        leftLayout = QVBoxLayout()

        leftLayout.addWidget(self.ipLabel)
        leftLayout.addWidget(self.ipEdit)

        leftLayout.addWidget(self.userLabel)
        leftLayout.addWidget(self.userEdit)

        leftLayout.addWidget(self.passLabel)
        leftLayout.addWidget(self.passEdit)

        leftLayout.addSpacing(10)

        leftLayout.addWidget(self.portLabel)
        leftLayout.addWidget(self.portEdit)

        leftLayout.addSpacing(10)

        leftLayout.addWidget(self.decLabel)
        leftLayout.addWidget(self.decBox)

        leftLayout.addWidget(self.triggerLabel)
        leftLayout.addWidget(self.triggerBox)

        leftLayout.addWidget(self.delayLabel)
        leftLayout.addWidget(self.delayBox)

        leftLayout.addSpacing(15)

        leftLayout.addWidget(self.connectButton)
        leftLayout.addWidget(self.triggerButton)
        leftLayout.addWidget(self.contButton)
        leftLayout.addWidget(self.stopButton)

        leftLayout.addStretch()

        ###############################################################

        rightLayout = QVBoxLayout()

        rightLayout.addWidget(
            self.plotCH1
        )

        rightLayout.addWidget(
            self.plotCH2
        )

        ###############################################################

        layout = QHBoxLayout()

        layout.addLayout(
            leftLayout,
            1
        )

        layout.addLayout(
            rightLayout,
            4
        )

        self.setLayout(layout)

        ###############################################################
        # Signals
        ###############################################################

        self.connectButton.clicked.connect(
            self.connectSSH
        )

        self.triggerButton.clicked.connect(
            self.startTrigger
        )

        self.contButton.clicked.connect(
            self.startContinuous
        )

        self.stopButton.clicked.connect(
            self.stopAcquisition
        )

    #################################################################
    # SSH
    #################################################################

    def connectSSH(self):

        from ssh_client import SSHController

        if self.ssh is not None:

            self.ssh.close()

        self.ssh = SSHController(

            host=self.ipEdit.text(),

            username=self.userEdit.text(),

            password=self.passEdit.text()

        )

        ok = self.ssh.connect()

        if ok:

            QMessageBox.information(
                self,
                "SSH",
                "Connected."
            )

        else:

            QMessageBox.critical(
                self,
                "SSH",
                "Connection failed."
            )

    #################################################################

    def startReceiver(self):

        if self.receiver is not None:

            return

        from receiver import ReceiverWorker

        self.receiver = ReceiverWorker(

            port=self.portEdit.value()

        )

        self.receiver.signals.data.connect(
            self.updatePlot
        )

        self.receiver.signals.finished.connect(
            self.receiverFinished
        )

        self.threadpool.start(
            self.receiver
        )

    #################################################################

    def receiverFinished(self):

        self.receiver = None

    #################################################################

    def startTrigger(self):

        self.startReceiver()

        if self.ssh is None:

            self.connectSSH()

        command = (
            "python3 /root/rp_stream.py "
            "--mode trigger "
            f"--host {self.getLocalIP()} "
            f"--port {self.portEdit.value()} "
            f"--dec {self.decBox.currentText()} "
            f"--trigger {self.triggerBox.value()} "
            f"--delay {self.delayBox.value()} "
        )

        self.ssh.exec_background(command)

    #################################################################

    def startContinuous(self):

        self.startReceiver()

        if self.ssh is None:

            self.connectSSH()

        command = (
            "python3 /root/rp_stream.py "
            "--mode continuous "
            f"--host {self.getLocalIP()} "
            f"--port {self.portEdit.value()} "
            f"--dec {self.decBox.currentText()} "
        )

        self.ssh.exec_background(command)

        #################################################################
    # Stop acquisition
    #################################################################

    def stopAcquisition(self):

        if self.ssh is not None:

            try:

                self.ssh.exec(
                    "pkill -f rp_stream.py"
                )

            except Exception as e:

                print(e)

        if self.receiver is not None:

            self.receiver.stop()

    #################################################################
    # Update plots
    #################################################################

    @pyqtSlot(object)
    def updatePlot(self, data):

        ch1, ch2 = data

        ch1 = (
            ch1.astype(np.float32) + 168
        ) / 8191.0 * 20

        ch2 = (
            ch2.astype(np.float32) + 168
        ) / 8191.0 * 20

        self.curve1.setData(ch1)

        self.curve2.setData(ch2)

    #################################################################
    # Local IP
    #################################################################

    def getLocalIP(self):

        import socket

        s = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM
        )

        try:

            s.connect(
                (
                    "8.8.8.8",
                    80
                )
            )

            ip = s.getsockname()[0]

        finally:

            s.close()

        return ip

    #################################################################
    # Window close
    #################################################################

    def closeEvent(self, event):

        self.stopAcquisition()

        if self.ssh is not None:

            self.ssh.close()

        event.accept()


#####################################################################
# Main
#####################################################################

if __name__ == "__main__":

    app = QApplication(sys.argv)

    window = MainWindow()

    window.show()

    sys.exit(
        app.exec_()
    )