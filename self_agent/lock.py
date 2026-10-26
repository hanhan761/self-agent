import os
from pathlib import Path

class ProcessLock:
    def __init__(self,path):self.path=Path(path);self.file=None
    def __enter__(self):
        self.file=self.path.open('a+b')
        self.file.seek(0);self.file.write(b'0');self.file.flush();self.file.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError('another_self_agent_instance_is_running') from None
        return self
    def __exit__(self,*args):
        self.file.close()
