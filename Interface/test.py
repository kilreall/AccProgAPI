import paramiko

HOST = "192.168.1.100"
USER = "root"
PASSWORD = "root"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

client.connect(
    hostname=HOST,
    username=USER,
    password=PASSWORD
)

stdin, stdout, stderr = client.exec_command(
    "python3 /root/my_script.py"
)

print("STDOUT:")
print(stdout.read().decode())

print("STDERR:")
print(stderr.read().decode())

client.close()