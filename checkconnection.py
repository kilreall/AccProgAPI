#!/usr/bin/python3


import socket


s = socket.socket()
s.settimeout(5)

s.connect(("192.168.55.224",5000))

print("connected")