# File: backend/app/integrations/html_source_reader.py
# Summary: Provides a thread-safe, restartable Python client for the vendored frozen HTML Source Reader JSONL worker.
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import subprocess
import threading
from typing import Any
from uuid import uuid4


DEFAULT_WORKER = Path(
    "/opt/fisora/html-reader/integration/fisora-html-reader-jsonl-worker.mjs"
)
RESTARTABLE_CODES = {
    "HTML_SOURCE_WORKER_CLOSED",
    "HTML_SOURCE_WORKER_TIMEOUT",
    "HTML_SOURCE_WORKER_PROTOCOL_ERROR",
}


class HtmlSourceReaderClientError(RuntimeError):
    """Raised when the persistent Node reader cannot return a valid response."""

    def __init__(self, message: str, *, code: str = "HTML_SOURCE_READER_ERROR") -> None:
        super().__init__(message)
        self.code = code


class PersistentHtmlReaderClient:
    """Own one Node subprocess and correlate concurrent JSONL requests by ID."""

    def __init__(self, root: Path, *, worker: Path, timeout_seconds: float = 10.0) -> None:
        self.root = root.resolve()
        self.worker = worker
        self.timeout_seconds = timeout_seconds
        self._process: subprocess.Popen[str] | None = None
        self._write_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._pending: dict[str, queue.Queue[dict[str, Any]]] = {}
        self._reader_thread: threading.Thread | None = None

    def _start(self) -> None:
        with self._state_lock:
            if self._process is not None and self._process.poll() is None:
                return
            self._process = subprocess.Popen(
                ["node", str(self.worker), "--root", str(self.root)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
            self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
            self._reader_thread.start()

    def _read_loop(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            try:
                response = json.loads(line)
                request_id = str(response.get("id") or "")
            except (json.JSONDecodeError, AttributeError):
                self._fail_pending("HTML_SOURCE_WORKER_PROTOCOL_ERROR", "invalid JSONL response")
                return
            with self._state_lock:
                waiter = self._pending.pop(request_id, None)
            if waiter is not None:
                waiter.put(response)
        self._fail_pending("HTML_SOURCE_WORKER_CLOSED", "HTML reader worker closed")

    def _fail_pending(self, code: str, message: str) -> None:
        with self._state_lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for waiter in pending:
            waiter.put({"ok": False, "error": {"code": code, "message": message}})

    def read(self, file_path: Path) -> dict[str, Any]:
        self._start()
        process = self._process
        if process is None or process.stdin is None or process.poll() is not None:
            raise HtmlSourceReaderClientError("HTML reader worker unavailable", code="HTML_SOURCE_WORKER_CLOSED")
        request_id = str(uuid4())
        waiter: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        with self._state_lock:
            self._pending[request_id] = waiter
        try:
            request = json.dumps({"id": request_id, "file": str(file_path.resolve())}, ensure_ascii=False)
            with self._write_lock:
                process.stdin.write(request + "\n")
                process.stdin.flush()
            try:
                response = waiter.get(timeout=self.timeout_seconds)
            except queue.Empty as exc:
                with self._state_lock:
                    self._pending.pop(request_id, None)
                raise HtmlSourceReaderClientError(
                    "HTML reader worker timed out", code="HTML_SOURCE_WORKER_TIMEOUT"
                ) from exc
        except (BrokenPipeError, OSError) as exc:
            with self._state_lock:
                self._pending.pop(request_id, None)
            raise HtmlSourceReaderClientError(
                "HTML reader worker closed", code="HTML_SOURCE_WORKER_CLOSED"
            ) from exc
        if not response.get("ok"):
            error = response.get("error") if isinstance(response.get("error"), dict) else {}
            raise HtmlSourceReaderClientError(
                str(error.get("message") or "HTML source reader failed"),
                code=str(error.get("code") or "HTML_SOURCE_READER_ERROR"),
            )
        return {
            "relativePath": str(response.get("relativePath") or ""),
            "snapshot": dict(response.get("snapshot") or {}),
        }

    def close(self) -> None:
        with self._state_lock:
            process = self._process
            self._process = None
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
        except OSError:
            pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        self._fail_pending("HTML_SOURCE_WORKER_CLOSED", "HTML reader worker closed")


class RestartingHtmlSourceReader:
    """Lazily starts the persistent reader and performs one controlled restart on transport failure."""

    reader_version = "1.0.0"

    def __init__(self, *, root: Path, worker: Path = DEFAULT_WORKER, timeout_seconds: float = 10.0) -> None:
        self.root = root
        self.worker = worker
        self.timeout_seconds = timeout_seconds
        self._client: PersistentHtmlReaderClient | None = None
        self._lifecycle_lock = threading.Lock()

    def _get_client(self) -> PersistentHtmlReaderClient:
        with self._lifecycle_lock:
            if self._client is None:
                self._client = PersistentHtmlReaderClient(
                    self.root,
                    worker=self.worker,
                    timeout_seconds=self.timeout_seconds,
                )
            return self._client

    def _restart(self) -> None:
        with self._lifecycle_lock:
            client = self._client
            self._client = None
        if client is not None:
            client.close()

    def read(self, file_path: Path) -> dict[str, Any]:
        for attempt in range(2):
            try:
                return self._get_client().read(file_path)
            except HtmlSourceReaderClientError as exc:
                if attempt == 0 and exc.code in RESTARTABLE_CODES:
                    self._restart()
                    continue
                raise
        raise HtmlSourceReaderClientError("HTML source reader failed after restart")


def build_html_source_reader_from_env() -> RestartingHtmlSourceReader:
    """Build the production reader from explicit worker/storage environment settings."""

    root = Path(os.environ.get("FISORA_DOCUMENT_STORAGE_PATH", "backend/data/documents"))
    worker = Path(os.environ.get("FISORA_HTML_READER_WORKER", str(DEFAULT_WORKER)))
    timeout_seconds = float(os.environ.get("FISORA_HTML_READER_TIMEOUT_SECONDS", "10"))
    return RestartingHtmlSourceReader(root=root, worker=worker, timeout_seconds=timeout_seconds)
