import paramiko


class SSHController:

    def __init__(self, host, username="root", password="root", port=22):

        self.host = host
        self.username = username
        self.password = password
        self.port = port

        self.client = None

    ##################################################################

    def connect(self):

        try:

            self.client = paramiko.SSHClient()

            self.client.set_missing_host_key_policy(
                paramiko.AutoAddPolicy()
            )

            self.client.connect(

                hostname=self.host,

                port=self.port,

                username=self.username,

                password=self.password,

                timeout=5

            )

            return True

        except Exception as e:

            print("SSH:", e)

            self.client = None

            return False

    ##################################################################

    def exec(self, command):

        if self.client is None:

            raise RuntimeError("SSH is not connected")

        print("SSH >", command)

        stdin, stdout, stderr = self.client.exec_command(command)

        err = stderr.read().decode()

        out = stdout.read().decode()

        if out:

            print(out)

        if err:

            print(err)

        return out, err

    ##################################################################

    def exec_background(self, command):

        """
        Запуск процесса без ожидания окончания.
        Именно этим методом нужно запускать rp_stream.py
        """

        if self.client is None:

            raise RuntimeError("SSH is not connected")

        transport = self.client.get_transport()

        channel = transport.open_session()

        channel.exec_command(command)

        return channel

    ##################################################################

    def kill_stream(self):

        if self.client is None:

            return

        self.exec("pkill -f rp_stream.py")

    ##################################################################

    def is_connected(self):

        if self.client is None:

            return False

        transport = self.client.get_transport()

        if transport is None:

            return False

        return transport.is_active()

    ##################################################################

    def close(self):

        if self.client is not None:

            self.client.close()

            self.client = None