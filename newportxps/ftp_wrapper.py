#!/usr/bin/env python

import ftplib
from io import BytesIO
from .utils import str2bytes, bytes2str, ENCODING

import logging
logger = logging.getLogger('paramiko')
logger.setLevel(logging.ERROR)


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

        if not HAS_PYSFTP:
            raise ValueError("pysftp not installed.")
        try:
            self._conn = pysftp.Connection(self.host,
                                           username=self.username,
                                           password=self.password)
        except:
            print("ERROR: sftp connection to %s failed" % self.host)
            print("You may need to add the host keys for your XPS to your")
            print("ssh known_hosts file, using a command like this:")
            print("  ssh-keyscan %s >> ~/.ssh/known_hosts" % self.host)


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
