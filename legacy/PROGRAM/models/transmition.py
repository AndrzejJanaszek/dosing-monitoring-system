from enum import Enum


class TransmitionFormat(Enum):
    ASCII = 'asci'  # "\x02{msg}\x03"
    LINE =  'line'  # "{msg}\n"
    CRLF =  'crlf'  # "{msg}\r\n"