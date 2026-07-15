import paramiko

HOST = "rp-f05e99.local"
USER = "root"
PASSWORD = "root"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

client.connect(
    hostname=HOST,
    username=USER,
    password=PASSWORD
)

cmd = "PYTHONPATH=/opt/redpitaya/lib/python:$PYTHONPATH /usr/bin/python3 /root/stream.py"



stdin, stdout, stderr = client.exec_command(
    cmd
)

print("STDOUT:")
print(stdout.read().decode())

print("STDERR:")
print(stderr.read().decode())

client.close()