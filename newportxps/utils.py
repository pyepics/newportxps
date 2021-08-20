
# it appears ftp really wants this encoding:
ENCODING = 'latin-1'

def bytes2str(s):
    'byte to string conversion'
    if isinstance(s, str):
        return s
    elif isinstance(s, bytes):
        return str(s, ENCODING)
    else:
        return str(s)

def str2bytes(s):
    'string to bytes conversion'
    if isinstance(s, bytes):
        return s
    elif isinstance(s, str):
        return s.encode(ENCODING)
    else:
        return bytes(str(s), ENCODING)
    
