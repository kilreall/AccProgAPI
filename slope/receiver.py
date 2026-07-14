import socket
import struct

import numpy as np

from PyQt5.QtCore import (
    QObject,
    QRunnable,
    pyqtSignal,
    pyqtSlot
)

##############################################################################

HEADER_MAGIC = 0x52503031

HEADER_SIZE = 16

N = 16384

PAYLOAD_SIZE = N * 2 * 2

##############################################################################

class ReceiverSignals(QObject):

    data = pyqtSignal(object)

    finished = pyqtSignal()

##############################################################################

class ReceiverWorker(QRunnable):

    def __init__(self, port):

        super().__init__()

        self.port = port

        self.running = True

        self.server = None

        self.conn = None

        self.signals = ReceiverSignals()

    ##########################################################################

    def stop(self):

        self.running = False

        try:

            if self.conn:

                self.conn.shutdown(socket.SHUT_RDWR)

        except:

            pass

        try:

            if self.conn:

                self.conn.close()

        except:

            pass

        try:

            if self.server:

                self.server.close()

        except:

            pass

    ##########################################################################

    @pyqtSlot()
    def run(self):

        self.server = socket.socket(

            socket.AF_INET,

            socket.SOCK_STREAM

        )

        self.server.setsockopt(

            socket.SOL_SOCKET,

            socket.SO_REUSEADDR,

            1

        )

        self.server.bind(

            ("0.0.0.0", self.port)

        )

        self.server.listen(1)

        self.server.settimeout(1)

        print(

            "Waiting RP..."

        )

        while self.running:

            try:

                self.conn, addr = self.server.accept()

                print(

                    "Connected",

                    addr

                )

                self.receiveLoop()

            except socket.timeout:

                continue

            except Exception as e:

                print(e)

        self.signals.finished.emit()

    ##########################################################################

    def receiveLoop(self):

        buffer = bytearray()

        while self.running:

            try:

                data = self.conn.recv(

                    65536

                )

            except:

                break

            if not data:

                break

            buffer.extend(data)

            while len(buffer) >= HEADER_SIZE:

                header = buffer[:HEADER_SIZE]

                magic, payload_size, packet_id, mode = struct.unpack(

                    "<IIII",

                    header

                )

                if magic != HEADER_MAGIC:

                    print(

                        "Wrong header"

                    )

                    buffer.clear()

                    break

                packet_size = HEADER_SIZE + payload_size

                if len(buffer) < packet_size:

                    break

import socket
import struct

import numpy as np

from PyQt5.QtCore import (
    QObject,
    QRunnable,
    pyqtSignal,
    pyqtSlot
)

##############################################################################

HEADER_MAGIC = 0x52503031

HEADER_SIZE = 16

N = 16384

PAYLOAD_SIZE = N * 2 * 2

##############################################################################

class ReceiverSignals(QObject):

    data = pyqtSignal(object)

    finished = pyqtSignal()

##############################################################################

class ReceiverWorker(QRunnable):

    def __init__(self, port):

        super().__init__()

        self.port = port

        self.running = True

        self.server = None

        self.conn = None

        self.signals = ReceiverSignals()

    ##########################################################################

    def stop(self):

        self.running = False

        try:

            if self.conn:

                self.conn.shutdown(socket.SHUT_RDWR)

        except:

            pass

        try:

            if self.conn:

                self.conn.close()

        except:

            pass

        try:

            if self.server:

                self.server.close()

        except:

            pass

    ##########################################################################

    @pyqtSlot()
    def run(self):

        self.server = socket.socket(

            socket.AF_INET,

            socket.SOCK_STREAM

        )

        self.server.setsockopt(

            socket.SOL_SOCKET,

            socket.SO_REUSEADDR,

            1

        )

        self.server.bind(

            ("0.0.0.0", self.port)

        )

        self.server.listen(1)

        self.server.settimeout(1)

        print(

            "Waiting RP..."

        )

        while self.running:

            try:

                self.conn, addr = self.server.accept()

                print(

                    "Connected",

                    addr

                )

                self.receiveLoop()

            except socket.timeout:

                continue

            except Exception as e:

                print(e)

        self.signals.finished.emit()

    ##########################################################################

    def receiveLoop(self):

        buffer = bytearray()

        while self.running:

            try:

                data = self.conn.recv(

                    65536

                )

            except:

                break

            if not data:

                break

            buffer.extend(data)

            while len(buffer) >= HEADER_SIZE:

                header = buffer[:HEADER_SIZE]

                magic, payload_size, packet_id, mode = struct.unpack(

                    "<IIII",

                    header

                )

                if magic != HEADER_MAGIC:

                    print(

                        "Wrong header"

                    )

                    buffer.clear()

                    break

                packet_size = HEADER_SIZE + payload_size

                if len(buffer) < packet_size:

                    break