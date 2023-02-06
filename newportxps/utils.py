
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

def read_xps_file(fname):
    """read file written by XPS, decoding bytes as latin-1"""
    with open(fname, 'rb') as fh:
        data = fh.read()
    return data.decode(ENCODING)

def clean_text(text):
    buff = []
    for line in text.split('\n'):
        line = line.replace('\r', '').replace('\n', '') + ' '
        buff.append(line)
    return '\n'.join(buff)
