
# it appears ftp really wants this encoding:
ENCODING = 'latin-1'

def bytes2str(s):
    'byte to string conversion'
    if isinstance(s, str):
        return s
    if isinstance(s, bytes):
        return str(s, ENCODING)
    else:
        return str(s)

def str2bytes(s):
    'string to bytes conversion'
    if isinstance(s, bytes):
        return s
    if not isinstance(s, str):
        s = str(s)
    return s.encode(ENCODING)
