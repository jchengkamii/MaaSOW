"""自动帮助与前台用例之间的跨进程互斥锁。"""

from __future__ import annotations

import msvcrt
import time
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[4]
LOCK_PATH = PROJECT_DIR / "cache" / "automation_execution.lock"


class AutomationMutex:
    """跨进程执行锁，防止后台辅助与普通用例同时操作游戏。"""

    def __init__(self) -> None:
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._file = LOCK_PATH.open("a+b")
        self._file.seek(0, 2)
        if self._file.tell() == 0:
            self._file.write(b"\0")
            self._file.flush()
        self._locked = False

    def acquire(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            self._file.seek(0)
            try:
                msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
                self._locked = True
                return True
            except OSError:
                if deadline is not None and time.monotonic() >= deadline:
                    return False
                time.sleep(0.1)

    def release(self) -> None:
        if not self._locked:
            return
        self._file.seek(0)
        msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
        self._locked = False

    def close(self) -> None:
        self.release()
        self._file.close()

    def __enter__(self) -> "AutomationMutex":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
