"""Process locks released by the OS after termination; no expiring write leases."""
from contextlib import contextmanager
from pathlib import Path
import os
import time


@contextmanager
def process_lock(path, *, wait_seconds=0):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        handle.seek(0,2)
        if handle.tell()==0:
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        end = time.monotonic()+wait_seconds
        while True:
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic()>=end: raise ValueError('process_already_running') from None
                time.sleep(.01)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)

