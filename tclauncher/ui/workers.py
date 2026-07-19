"""Small helpers to run blocking work off the GUI thread."""

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot


class _WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(Exception)
    progress = Signal(float)
    # Emitted (queued) once run() completes, so cleanup happens on the main
    # thread after every other queued slot for this worker has been delivered.
    done = Signal()


# Workers must stay referenced until their queued signals have been delivered
# on the main thread. QThreadPool keeps no reference to the Python wrapper, and
# the worker/signals QObject must outlive the cross-thread queued emit: freeing
# it in run() (on the pool thread) leaves Qt delivering posted events to a dead
# object, which segfaults inside Shiboken.
_active_workers: set["Worker"] = set()


class Worker(QRunnable):
    """Runs fn(*args, **kwargs) on the global thread pool.

    If fn accepts an `on_progress` kwarg, it receives a callable emitting the
    progress signal (0.0-1.0).
    """

    def __init__(self, fn, *args, with_progress: bool = False, **kwargs):
        super().__init__()
        # Manage lifetime from Python; do not let Qt auto-delete the C++ side
        # of this QRunnable when run() returns.
        self.setAutoDelete(False)
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = _WorkerSignals()
        if with_progress:
            self.kwargs["on_progress"] = self.signals.progress.emit

    def run(self):
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as e:
            self._emit(self.signals.failed, e)
        else:
            self._emit(self.signals.finished, result)
        finally:
            # Cross-thread emit: only posts an event. Cleanup runs later on the
            # main thread via the queued `done` slot, keeping this worker (and
            # its signals) alive until all its posted events are delivered.
            self._emit(self.signals.done)

    @staticmethod
    def _emit(signal, *args):
        try:
            signal.emit(*args)
        except RuntimeError:
            # The receiving QObject was destroyed (e.g. the app is shutting down
            # while this worker was still running). Nothing to deliver to.
            pass


def run_worker(fn, *args, on_finished=None, on_failed=None, on_progress=None, **kwargs) -> Worker:
    worker = Worker(fn, *args, with_progress=on_progress is not None, **kwargs)
    if on_finished is not None:
        worker.signals.finished.connect(on_finished)
    if on_failed is not None:
        worker.signals.failed.connect(on_failed)
    if on_progress is not None:
        worker.signals.progress.connect(on_progress)

    @Slot()
    def _cleanup():
        _active_workers.discard(worker)

    # Force a queued connection so cleanup is delivered on the main thread,
    # ordered after the finished/failed slots already posted from run().
    worker.signals.done.connect(_cleanup, Qt.QueuedConnection)

    _active_workers.add(worker)
    QThreadPool.globalInstance().start(worker)
    return worker
