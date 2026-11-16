"""Send a finite fixture request together, including against early HTTP denials.

Windows can abort an HTTP/1.0 socket when the server rejects headers and closes
before http.client's separate body write. Coalescing preserves the exact request
and the actual response. No retry, error swallowing or synthetic response.
"""
import http.client


class CompleteRequestConnection(http.client.HTTPConnection):
    def _send_output(self, message_body=None, encode_chunked=False):
        if isinstance(message_body, (bytes, bytearray)) and not encode_chunked:
            self._buffer.extend((b'', b''))
            request = b'\r\n'.join(self._buffer)+bytes(message_body)
            self._buffer.clear()
            self.send(request)
        else:
            super()._send_output(message_body, encode_chunked)
