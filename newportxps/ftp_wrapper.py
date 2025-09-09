#!/usr/bin/env python

import ftplib
from io import BytesIO
from .utils import str2bytes, bytes2str, ENCODING

import logging
logger = logging.getLogger('paramiko')
logger.setLevel(logging.ERROR)


SFTP_ERROR_MESSAGE = """Could not connect to XPS with sftp: no host key.

You may need to add a host key to your `ssh known_hosts` file, using
   ssh-keyscan {host} >> ~/.ssh/known_hosts

or first connecting with  `sftp Administrator@{host}` """

import paramiko

HAS_PYSFTP = False
try:
    import pysftp
    HAS_PYSFTP = True
except ImportError:
    pass

class FTPBaseWrapper(object):
    """base clase for ftp interactions for Newport XPS
    needs to be overwritten -- use SFTPWrapper or FTPWrapper"""
    def __init__(self, host=None, username='Administrator',
                 password='Administrator'):
        self.host = host
        self.username = username
        self.password = password
        self._conn = None

    def close(self):
        if self._conn is not None:
            self._conn.close()
        self._conn = None

    def cwd(self, remotedir):
        self._conn.cwd(remotedir)

    def connect(self, host=None, username=None, password=None):
        raise NotImplementedError

    def save(self, remotefile, localfile):
        "save remote file to local file"
        raise NotImplementedError

    def getlines(self, remotefile):
        "read text of remote file"
        raise NotImplementedError

    def put(self, text, remotefile):
        "put text to remote file"
        raise NotImplementedError


class SFTPWrapper(FTPBaseWrapper):
    """wrap ftp interactions for Newport XPS models D"""
    def __init__(self, host=None, username='Administrator',
                 password='Administrator', use_paramiko=True):
        self.use_paramiko = use_paramiko
        self.ssh_client = None
        FTPBaseWrapper.__init__(self, host=host,
                                username=username, password=password)

    def connect(self, host=None, username=None, password=None):
        if host is not None:
            self.host = host
        if username is not None:
            self.username = username
        if password is not None:
            self.password = password
        if not self.use_paramiko and HAS_PYSFTP:
            self._conn = pysftp.Connection(host,
                                           username=username,
                                           password=password)
        else:
            if self.ssh_client is None:
                self.ssh_client = paramiko.SSHClient()
                self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            try:
                self.ssh_client.connect(host, 22, username, password)

            except paramiko.AuthenticationException:
                print("Authentication failed. Check your username and password/key.")
                raise ValueError(SFTP_ERROR_MESSAGE.format(host=self.host))
            except paramiko.SSHException as e:
                print(f"SSH connection error: {e}")
                raise ValueError(SFTP_ERROR_MESSAGE.format(host=self.host))
            finally:
                self._conn = self.ssh_client.open_sftp()

    def cwd(self, remotedir):
        if self.use_paramiko:
            self._conn.chdir(remotedir)
        elif hasattr(self._conn, 'cwd'):
            self._conn.cwd(remotedir)

    def save(self, remotefile, localfile):
        "save remote file to local file"
        self._conn.get(remotefile, localfile)

    def getlines(self, remotefile):
        "read text of remote file"
        tmp = BytesIO()
        self._conn.getfo(remotefile, tmp)
        tmp.seek(0)
        text = bytes2str(tmp.read())
        return text.split('\n')

    def put(self, text, remotefile):
        txtfile = BytesIO(str2bytes(text))
        self._conn.putfo(txtfile, remotefile)


class FTPWrapper(FTPBaseWrapper):
    """wrap ftp interactions for Newport XPS models C and Q"""
    def __init__(self, host=None, username='Administrator',
                 password='Administrator'):
        FTPBaseWrapper.__init__(self, host=host,
                                username=username, password=password)

    def connect(self, host=None, username=None, password=None):
        if host is not None:
            self.host = host
        if username is not None:
            self.username = username
        if password is not None:
            self.password = password

        self._conn = ftplib.FTP()
        self._conn.connect(self.host)
        self._conn.login(self.username, self.password)

    def list(self):
        "list files in a given directory (default the current)"
        return self._conn.nlst()

    def save(self, remotefile, localfile):
        "save remote file to local file"
        output = []
        self._conn.retrbinary(f'RETR {remotefile}', output.append)
        with open(localfile, 'w', encoding=ENCODING) as fout:
            fout.write(''.join([bytes2str(s) for s in output]))

    def getlines(self, remotefile):
        "read text of remote file"
        output = []
        self._conn.retrbinary('RETR %s' % remotefile, output.append)
        text = ''.join([bytes2str(line) for line in output])
        return text.split('\n')

    def put(self, text, remotefile):
        txtfile = BytesIO(str2bytes(text))
        self._conn.storbinary('STOR %s' % remotefile, txtfile)

    def delete(self, remotefile):
        "delete remote file"
        self._conn.delete(remotefile)
