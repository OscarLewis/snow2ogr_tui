import time
from dataclasses import dataclass, field

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Container, Vertical
from textual.message import Message
from textual.widgets import Label, Static
from textual.worker import Worker


@dataclass
class DownloadProgress:
    """Track progress for a single download"""

    worker_id: str
    dataset_name: str
    rows_downloaded: int = 0
    total_rows: int = 0
    status: str = "pending"
    error: str | None = None

    @property
    def percentage(self) -> float:
        if self.total_rows == 0:
            return 0
        return (self.rows_downloaded / self.total_rows) * 100


class WorkerProgressTracker:
    """Manages multiple worker download tasks"""

    def __init__(self, app: "DownloadApp"):
        self.app = app
        self.workers: dict[str, DownloadProgress] = {}

    def register_download(self, dataset_name: str, total_rows: int) -> str:
        """Register a new download and return worker ID"""
        worker_id = f"{dataset_name}_{len(self.workers)}"
        self.workers[worker_id] = DownloadProgress(
            worker_id=worker_id,
            dataset_name=dataset_name,
            total_rows=total_rows,
        )
        return worker_id

    def update_progress(self, worker_id: str, rows: int):
        """Update progress for a worker"""
        if worker_id in self.workers:
            self.workers[worker_id].rows_downloaded = rows
            self.workers[worker_id].status = "running"

    def complete(self, worker_id: str):
        """Mark worker as complete"""
        if worker_id in self.workers:
            self.workers[worker_id].status = "completed"

    def error(self, worker_id: str, error_msg: str):
        """Mark worker as errored"""
        if worker_id in self.workers:
            self.workers[worker_id].status = "error"
            self.workers[worker_id].error = error_msg


class ProgressUpdateMessage(Message):
    """Custom message for progress updates"""

    def __init__(self, worker_id: str, progress: DownloadProgress):
        super().__init__()
        self.worker_id = worker_id
        self.progress = progress


class DownloadApp(App):
    """Example app with multiple concurrent Snowflake downloads"""

    def on_mount(self):
        self.tracker = WorkerProgressTracker(self)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Active Downloads:")
            with Container(id="downloads-container"):
                pass

    @work(thread=True)
    def download_dataset(self, dataset_name: str, worker_id: str) -> None:
        """Simulate downloading from Snowflake"""
        tracker = self.tracker
        worker = tracker.workers[worker_id]

        try:
            # Simulate Snowflake connection and download
            total_rows = 10000
            batch_size = 500

            for i in range(0, total_rows, batch_size):
                rows_downloaded = min(i + batch_size, total_rows)
                tracker.update_progress(worker_id, rows_downloaded)

                # Post update message (thread-safe)
                self.post_message(
                    ProgressUpdateMessage(worker_id, worker),
                )

                # Simulate fetch delay
                time.sleep(0.1)

            tracker.complete(worker_id)
            self.post_message(
                ProgressUpdateMessage(worker_id, worker),
            )

        except Exception as e:
            tracker.error(worker_id, str(e))
            self.post_message(
                ProgressUpdateMessage(worker_id, worker),
            )

    def action_start_downloads(self) -> None:
        """Start multiple concurrent downloads"""
        datasets = [
            ("sales_data", 50000),
            ("customer_data", 30000),
            ("transactions", 100000),
        ]

        for name, total in datasets:
            worker_id = self.tracker.register_download(name, total)
            self.download_dataset(name, worker_id)

    def on_progress_update_message(self, message: ProgressUpdateMessage) -> None:
        """Handle progress updates from workers"""
        progress = message.progress
        pct = progress.percentage

        # Update or create progress display
        container = self.query_one("#downloads-container", Container)

        # You could also use RichLog or DataTable for better visualization
        self.log(
            f"{progress.dataset_name}: {pct:.1f}% ({progress.rows_downloaded}/{progress.total_rows})",
        )
