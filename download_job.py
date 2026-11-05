"""Headless per-job entry point; never opens Tk or claims another queue item."""
import json
from pathlib import Path
import sys
import threading


class EventJournal:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()

    def put(self, event):
        with self.lock, self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=True) + "\n")


def main():
    import app
    index = sys.argv.index("--download-job")
    job_id, events_file = int(sys.argv[index + 1]), Path(sys.argv[index + 2])
    app.configure_logging()
    worker = app.DownloaderApp.__new__(app.DownloaderApp)
    worker.job_store = app.QueueStore(app.QUEUE_DB)
    worker.events = EventJournal(events_file)
    worker.language = worker.job_store.get_preference("language", "fa")
    worker.cancel_event = threading.Event()
    worker.output_candidates = set()
    worker.current_job_id = None
    worker.current_control = ""
    worker.last_control_check = worker.last_progress_save = worker.last_progress_event = 0.0
    job = worker.job_store.get(job_id)
    if job is not None:
        worker._run_claimed_job(job)
