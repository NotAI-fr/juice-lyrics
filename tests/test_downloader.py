from __future__ import annotations

import hashlib
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable

import pytest

from juice_lyrics.acquisition.downloader import DownloadPolicy, download_to
from juice_lyrics.acquisition.models import AcquisitionItem, AcquisitionState


class MockServerHandler(BaseHTTPRequestHandler):
    handler_callback: Callable[[BaseHTTPRequestHandler], None] | None = None

    def do_GET(self) -> None:
        if MockServerHandler.handler_callback:
            MockServerHandler.handler_callback(self)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass  # Suppress HTTP server stdout spam during tests


@pytest.fixture
def mock_http_server():
    server = HTTPServer(("127.0.0.1", 0), MockServerHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    base_url = f"http://127.0.0.1:{port}"

    def set_handler(func: Callable[[BaseHTTPRequestHandler], None]) -> None:
        MockServerHandler.handler_callback = func

    yield base_url, set_handler

    MockServerHandler.handler_callback = None
    server.shutdown()
    server.server_close()


def _make_item(base_url: str, dest: Path, **kwargs: Any) -> AcquisitionItem:
    return AcquisitionItem(
        identifier="test-1",
        title="Test Track",
        url=f"{base_url}/test.mp3",
        destination=dest,
        **kwargs,
    )


def test_downloader_successful_streaming(tmp_path, mock_http_server):
    base_url, set_handler = mock_http_server
    payload = b"Sample audio stream chunk 1. Sample audio stream chunk 2." * 10
    dest = tmp_path / "song.mp3"

    def handler(req: BaseHTTPRequestHandler):
        req.send_response(200)
        req.send_header("Content-Length", str(len(payload)))
        req.send_header("Content-Type", "audio/mpeg")
        req.end_headers()
        req.wfile.write(payload)

    set_handler(handler)
    item = _make_item(base_url, dest)
    policy = DownloadPolicy(require_https=False, chunk_size=32)

    result = download_to(item, policy)

    assert result.state is AcquisitionState.COMPLETE
    assert result.bytes_written == len(payload)
    assert result.destination == dest
    assert dest.is_file()
    assert dest.read_bytes() == payload
    assert not dest.with_name("song.mp3.part").exists()


def test_downloader_retries_on_503_and_succeeds(tmp_path, mock_http_server):
    base_url, set_handler = mock_http_server
    payload = b"Retry success audio data"
    dest = tmp_path / "song.mp3"
    request_count = 0

    def handler(req: BaseHTTPRequestHandler):
        nonlocal request_count
        request_count += 1
        if request_count < 3:
            req.send_response(503)
            req.end_headers()
            req.wfile.write(b"Service Unavailable")
        else:
            req.send_response(200)
            req.send_header("Content-Length", str(len(payload)))
            req.end_headers()
            req.wfile.write(payload)

    set_handler(handler)
    item = _make_item(base_url, dest)
    policy = DownloadPolicy(require_https=False, retries=3, retry_delay=0.01)

    result = download_to(item, policy)

    assert result.state is AcquisitionState.COMPLETE
    assert request_count == 3
    assert dest.read_bytes() == payload


def test_downloader_retries_exhausted_on_500(tmp_path, mock_http_server):
    base_url, set_handler = mock_http_server
    dest = tmp_path / "song.mp3"
    request_count = 0

    def handler(req: BaseHTTPRequestHandler):
        nonlocal request_count
        request_count += 1
        req.send_response(500)
        req.end_headers()
        req.wfile.write(b"Server Error")

    set_handler(handler)
    item = _make_item(base_url, dest)
    policy = DownloadPolicy(require_https=False, retries=2, retry_delay=0.01)

    result = download_to(item, policy)

    assert result.state is AcquisitionState.FAILED
    assert request_count == 3  # 1 initial + 2 retries
    assert not dest.exists()


def test_downloader_non_retryable_404_aborts_immediately(tmp_path, mock_http_server):
    base_url, set_handler = mock_http_server
    dest = tmp_path / "song.mp3"
    request_count = 0

    def handler(req: BaseHTTPRequestHandler):
        nonlocal request_count
        request_count += 1
        req.send_response(404)
        req.end_headers()
        req.wfile.write(b"Not Found")

    set_handler(handler)
    item = _make_item(base_url, dest)
    policy = DownloadPolicy(require_https=False, retries=3, retry_delay=0.01)

    result = download_to(item, policy)

    assert result.state is AcquisitionState.FAILED
    assert request_count == 1  # Aborted immediately on 404 without retries
    assert "404" in (result.error or "")


def test_downloader_non_retryable_403_aborts_immediately(tmp_path, mock_http_server):
    base_url, set_handler = mock_http_server
    dest = tmp_path / "song.mp3"
    request_count = 0

    def handler(req: BaseHTTPRequestHandler):
        nonlocal request_count
        request_count += 1
        req.send_response(403)
        req.end_headers()
        req.wfile.write(b"Forbidden")

    set_handler(handler)
    item = _make_item(base_url, dest)
    policy = DownloadPolicy(require_https=False, retries=3, retry_delay=0.01)

    result = download_to(item, policy)

    assert result.state is AcquisitionState.FAILED
    assert request_count == 1
    assert "403" in (result.error or "")


def test_downloader_range_resume_with_206(tmp_path, mock_http_server):
    base_url, set_handler = mock_http_server
    full_data = b"0123456789ABCDEF"
    part_data = b"0123456789"
    remaining = b"ABCDEF"
    dest = tmp_path / "song.mp3"
    partial = dest.with_name("song.mp3.part")
    partial.write_bytes(part_data)

    range_header_seen = None

    def handler(req: BaseHTTPRequestHandler):
        nonlocal range_header_seen
        range_header_seen = req.headers.get("Range")
        req.send_response(206)
        req.send_header("Content-Length", str(len(remaining)))
        req.send_header("Content-Range", f"bytes 10-15/{len(full_data)}")
        req.end_headers()
        req.wfile.write(remaining)

    set_handler(handler)
    item = _make_item(base_url, dest)
    policy = DownloadPolicy(require_https=False, resume=True)

    result = download_to(item, policy)

    assert range_header_seen == "bytes=10-"
    assert result.state is AcquisitionState.COMPLETE
    assert result.resumed is True
    assert dest.read_bytes() == full_data
    assert not partial.exists()


def test_downloader_server_ignoring_range_returns_200(tmp_path, mock_http_server):
    base_url, set_handler = mock_http_server
    full_data = b"FULL_PAYLOAD_FROM_START"
    dest = tmp_path / "song.mp3"
    partial = dest.with_name("song.mp3.part")
    partial.write_bytes(b"STALE_PREFIX")

    def handler(req: BaseHTTPRequestHandler):
        req.send_response(200)
        req.send_header("Content-Length", str(len(full_data)))
        req.end_headers()
        req.wfile.write(full_data)

    set_handler(handler)
    item = _make_item(base_url, dest)
    policy = DownloadPolicy(require_https=False, resume=True)

    result = download_to(item, policy)

    assert result.state is AcquisitionState.COMPLETE
    assert result.resumed is False
    assert dest.read_bytes() == full_data
    assert not partial.exists()


def test_downloader_http_416_recovers_by_restarting_from_zero(tmp_path, mock_http_server):
    base_url, set_handler = mock_http_server
    full_data = b"VALID_AUDIO_DATA"
    dest = tmp_path / "song.mp3"
    partial = dest.with_name("song.mp3.part")
    partial.write_bytes(b"CORRUPTED_OVERSIZED_PARTIAL_BYTES" * 10)

    request_count = 0

    def handler(req: BaseHTTPRequestHandler):
        nonlocal request_count
        request_count += 1
        if "Range" in req.headers:
            req.send_response(416)
            req.send_header("Content-Range", f"bytes */{len(full_data)}")
            req.end_headers()
        else:
            req.send_response(200)
            req.send_header("Content-Length", str(len(full_data)))
            req.end_headers()
            req.wfile.write(full_data)

    set_handler(handler)
    item = _make_item(base_url, dest)
    policy = DownloadPolicy(require_https=False, resume=True, retries=2, retry_delay=0.01)

    result = download_to(item, policy)

    assert result.state is AcquisitionState.COMPLETE
    assert request_count == 2
    assert dest.read_bytes() == full_data


def test_downloader_expected_size_mismatch_cleans_part_and_does_not_retry(tmp_path, mock_http_server):
    base_url, set_handler = mock_http_server
    actual_data = b"short"
    dest = tmp_path / "song.mp3"
    request_count = 0

    def handler(req: BaseHTTPRequestHandler):
        nonlocal request_count
        request_count += 1
        req.send_response(200)
        req.send_header("Content-Length", str(len(actual_data)))
        req.end_headers()
        req.wfile.write(actual_data)

    set_handler(handler)
    item = _make_item(base_url, dest, expected_size=100)
    policy = DownloadPolicy(require_https=False, retries=3, retry_delay=0.01)

    result = download_to(item, policy)

    assert result.state is AcquisitionState.FAILED
    assert request_count == 1  # Fatal validation failure -> no retries
    assert "size mismatch" in (result.error or "")
    assert not dest.exists()
    assert not dest.with_name("song.mp3.part").exists()


def test_downloader_sha256_mismatch_cleans_part_and_does_not_retry(tmp_path, mock_http_server):
    base_url, set_handler = mock_http_server
    payload = b"sample content"
    dest = tmp_path / "song.mp3"
    request_count = 0

    def handler(req: BaseHTTPRequestHandler):
        nonlocal request_count
        request_count += 1
        req.send_response(200)
        req.send_header("Content-Length", str(len(payload)))
        req.end_headers()
        req.wfile.write(payload)

    set_handler(handler)
    item = _make_item(base_url, dest, expected_sha256="0" * 64)
    policy = DownloadPolicy(require_https=False, retries=3, retry_delay=0.01)

    result = download_to(item, policy)

    assert result.state is AcquisitionState.FAILED
    assert request_count == 1  # Fatal checksum mismatch -> no retries
    assert "SHA-256" in (result.error or "")
    assert not dest.exists()
    assert not dest.with_name("song.mp3.part").exists()


def test_downloader_maximum_size_protection(tmp_path, mock_http_server):
    base_url, set_handler = mock_http_server
    payload = b"X" * 10000
    dest = tmp_path / "song.mp3"
    request_count = 0

    def handler(req: BaseHTTPRequestHandler):
        nonlocal request_count
        request_count += 1
        req.send_response(200)
        req.end_headers()
        req.wfile.write(payload)

    set_handler(handler)
    item = _make_item(base_url, dest)
    policy = DownloadPolicy(require_https=False, max_bytes=500, chunk_size=100, retries=2, retry_delay=0.01)

    result = download_to(item, policy)

    assert result.state is AcquisitionState.FAILED
    assert request_count == 1  # Fatal max_bytes error -> no retries
    assert "maximum size" in (result.error or "")
    assert not dest.exists()
    assert not dest.with_name("song.mp3.part").exists()


def test_downloader_rejects_html_error_payload(tmp_path, mock_http_server):
    base_url, set_handler = mock_http_server
    html_error = b"<!DOCTYPE html><html><body><h1>Error</h1></body></html>"
    dest = tmp_path / "song.mp3"

    def handler(req: BaseHTTPRequestHandler):
        req.send_response(200)
        req.end_headers()
        req.wfile.write(html_error)

    set_handler(handler)
    item = _make_item(base_url, dest)
    policy = DownloadPolicy(require_https=False, retries=0)

    result = download_to(item, policy)

    assert result.state is AcquisitionState.FAILED
    assert "error response" in (result.error or "")
    assert not dest.exists()
    assert not dest.with_name("song.mp3.part").exists()


def test_downloader_progress_callback(tmp_path, mock_http_server):
    base_url, set_handler = mock_http_server
    payload = b"1234567890ABCDEF"  # 16 bytes
    dest = tmp_path / "song.mp3"

    def handler(req: BaseHTTPRequestHandler):
        req.send_response(200)
        req.send_header("Content-Length", "16")
        req.end_headers()
        req.wfile.write(payload)

    set_handler(handler)
    item = _make_item(base_url, dest)
    policy = DownloadPolicy(require_https=False, chunk_size=4)

    progress_events = []

    def on_progress(written: int, total: int | None):
        progress_events.append((written, total))

    result = download_to(item, policy, progress=on_progress)

    assert result.state is AcquisitionState.COMPLETE
    assert progress_events == [(4, 16), (8, 16), (12, 16), (16, 16)]


def test_downloader_existing_matching_file_is_skipped(tmp_path, mock_http_server):
    base_url, set_handler = mock_http_server
    dest = tmp_path / "song.mp3"
    content = b"already downloaded content"
    dest.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()

    handler_called = False

    def handler(req: BaseHTTPRequestHandler):
        nonlocal handler_called
        handler_called = True

    set_handler(handler)
    item = _make_item(base_url, dest, expected_size=len(content), expected_sha256=digest)
    policy = DownloadPolicy(require_https=False, overwrite=False)

    result = download_to(item, policy)

    assert result.state is AcquisitionState.SKIPPED
    assert result.destination == dest
    assert result.bytes_written == len(content)
    assert handler_called is False
