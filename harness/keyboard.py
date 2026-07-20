"""Non-blocking console key capture for T2 operator marking (FR5).

Only the runner touches the keyboard; judges receive marks through a
queue so they stay testable without a console. msvcrt needs a real
console -- preflight asserts isatty for T2 runs.
"""

import queue
import sys
import threading
import time

WATCHED_KEYS = ("m", "c", "q")


class KeyListener:
    """Background thread pushing watched keypresses into a queue."""

    def __init__(self):
        self.events: queue.Queue[tuple[str, float]] = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        if sys.platform == "win32":
            self._loop_windows()
        else:
            self._loop_posix()

    def _loop_windows(self) -> None:
        import msvcrt

        while not self._stop.is_set():
            if msvcrt.kbhit():
                key = msvcrt.getwch().lower()
                if key in WATCHED_KEYS:
                    self.events.put((key, time.time()))
            else:
                time.sleep(0.05)

    def _loop_posix(self) -> None:
        # Dev-environment fallback (Git Bash / WSL); line-buffered.
        for line in sys.stdin:
            if self._stop.is_set():
                return
            key = line.strip().lower()[:1]
            if key in WATCHED_KEYS:
                self.events.put((key, time.time()))

    def drain(self) -> list[tuple[str, float]]:
        """All pending (key, epoch_time) events, oldest first."""
        drained = []
        while True:
            try:
                drained.append(self.events.get_nowait())
            except queue.Empty:
                return drained
