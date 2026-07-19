"""Regression test for the worker-lifetime segfault.

Cross-thread queued signals only post an event; the Worker (and its signals
QObject) must stay alive until that event is delivered on the main thread.
Freeing it on the pool thread crashes inside Shiboken. A crash aborts the
process, so we run the scenario in a subprocess and assert a clean exit.
"""
import subprocess
import sys
import textwrap

SCENARIO = textwrap.dedent(
    """
    import gc, sys, time
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from tclauncher.ui.workers import run_worker

    app = QApplication([])
    results = []

    def task():
        time.sleep(0.05)
        return "ok"

    def kick():
        for _ in range(20):
            run_worker(task, on_finished=lambda r: results.append(r))

    QTimer.singleShot(0, kick)
    churn = QTimer(); churn.timeout.connect(gc.collect); churn.start(20)
    QTimer.singleShot(1500, app.quit)
    app.exec()
    assert len(results) == 20, results
    print("SCENARIO_OK")
    """
)


def test_worker_signals_survive_until_delivered():
    proc = subprocess.run(
        [sys.executable, "-c", SCENARIO],
        capture_output=True,
        text=True,
        env={"QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": ".", "PATH": ""},
        timeout=60,
    )
    assert proc.returncode == 0, f"worker scenario crashed (rc={proc.returncode}): {proc.stderr[-2000:]}"
    assert "SCENARIO_OK" in proc.stdout
