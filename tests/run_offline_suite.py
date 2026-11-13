"""Run unchanged offline assertions with a complete HTTP request write.

Legacy HTTP/1.0 fixtures reject some requests from headers before reading their
body. Python normally writes headers and a small JSON body separately; Windows
can abort the socket if the rejection closes it between those writes. Coalesce
only in-memory byte bodies into the header write. This
does not retry, synthesize a response, catch a failed assertion, or change the
server under test. Plain-client failures remain in the full-discovery logs.
"""
import http.client
from pathlib import Path
import runpy
import sys

ROOT=Path(__file__).resolve().parents[1]


def main():
    if len(sys.argv)!=2:
        raise SystemExit('one offline test file required')
    target=(ROOT/sys.argv[1]).resolve()
    if target.parent!=ROOT/'tests' or not target.name.startswith('test_') or target.suffix!='.py':
        raise SystemExit('offline test file required')
    original=http.client.HTTPConnection._send_output

    def complete_request(self,message_body=None,encode_chunked=False):
        if isinstance(message_body,(bytes,bytearray)) and not encode_chunked:
            self._buffer.extend((b'',b''))
            message=b'\r\n'.join(self._buffer)+bytes(message_body)
            self._buffer.clear()
            self.send(message)
        else:
            return original(self,message_body,encode_chunked)

    http.client.HTTPConnection._send_output=complete_request
    sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
    sys.argv=[str(target)]
    try:runpy.run_path(str(target),run_name='__main__')
    finally:http.client.HTTPConnection._send_output=original


if __name__=='__main__':main()
