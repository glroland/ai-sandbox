"""Tests for the /convert and /convert/text endpoints.

Both endpoints return a StreamingResponse (text/plain, chunked).
The TestClient buffers the full stream before returning, so response.text
contains the complete body — we assert on that directly.

converter.stream_to_markdown is patched for all tests so the suite runs
without docling installed.
"""

from collections.abc import AsyncGenerator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PDF_BYTES = b"%PDF-1.4 stub"
_HEADERS = {"Content-Type": "application/octet-stream"}


async def _md_gen(*pages: str) -> AsyncGenerator[str, None]:
    for page in pages:
        yield page


# ---------------------------------------------------------------------------
# POST /convert/  — validation
# ---------------------------------------------------------------------------

def test_unsupported_extension_returns_415(client: TestClient) -> None:
    response = client.post(
        "/convert/?filename=report.xyz",
        content=_PDF_BYTES,
        headers=_HEADERS,
    )
    assert response.status_code == 415


def test_missing_filename_returns_422(client: TestClient) -> None:
    response = client.post("/convert/", content=_PDF_BYTES, headers=_HEADERS)
    assert response.status_code == 422


def test_batch_size_zero_returns_422(client: TestClient) -> None:
    response = client.post(
        "/convert/?filename=report.pdf&page_batch_size=0",
        content=_PDF_BYTES,
        headers=_HEADERS,
    )
    assert response.status_code == 422


def test_batch_size_over_max_returns_422(client: TestClient) -> None:
    response = client.post(
        "/convert/?filename=report.pdf&page_batch_size=999",
        content=_PDF_BYTES,
        headers=_HEADERS,
    )
    assert response.status_code == 422


def test_file_too_large_returns_413(client: TestClient) -> None:
    from app.config import settings

    oversized = b"x" * (settings.max_file_size_mb * 1024 * 1024 + 1)
    response = client.post(
        "/convert/?filename=big.pdf",
        content=oversized,
        headers=_HEADERS,
    )
    assert response.status_code == 413


# ---------------------------------------------------------------------------
# POST /convert/  — streaming markdown
# ---------------------------------------------------------------------------

@patch("app.routers.convert.converter.stream_to_markdown")
def test_streams_plain_text(mock_stream, client: TestClient) -> None:
    mock_stream.return_value = _md_gen("# Page 1\n\n", "## Page 2\n\n")

    response = client.post(
        "/convert/?filename=report.pdf",
        content=_PDF_BYTES,
        headers=_HEADERS,
    )

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "# Page 1" in response.text
    assert "## Page 2" in response.text


@patch("app.routers.convert.converter.stream_to_markdown")
def test_x_filename_header_present(mock_stream, client: TestClient) -> None:
    mock_stream.return_value = _md_gen("content")

    response = client.post(
        "/convert/?filename=annual-report.pdf",
        content=_PDF_BYTES,
        headers=_HEADERS,
    )

    assert response.headers.get("x-filename") == "annual-report.pdf"


@patch("app.routers.convert.converter.stream_to_markdown")
def test_batch_size_forwarded_to_generator(mock_stream, client: TestClient) -> None:
    mock_stream.return_value = _md_gen("text")

    client.post(
        "/convert/?filename=report.pdf&page_batch_size=4",
        content=_PDF_BYTES,
        headers=_HEADERS,
    )

    args, kwargs = mock_stream.call_args
    actual_batch = kwargs.get("page_batch_size", args[2] if len(args) > 2 else None)
    assert actual_batch == 4


@patch("app.routers.convert.converter.stream_to_markdown")
def test_docx_is_accepted(mock_stream, client: TestClient) -> None:
    mock_stream.return_value = _md_gen("## Section 1\n\n")

    response = client.post(
        "/convert/?filename=doc.docx",
        content=b"PK stub",
        headers=_HEADERS,
    )

    assert response.status_code == 200
    assert "## Section 1" in response.text


@patch("app.routers.convert.converter.stream_to_markdown")
def test_html_is_accepted(mock_stream, client: TestClient) -> None:
    mock_stream.return_value = _md_gen("content")

    response = client.post(
        "/convert/?filename=page.html",
        content=b"<html/>",
        headers=_HEADERS,
    )

    assert response.status_code == 200


@patch("app.routers.convert.converter.stream_to_markdown")
def test_image_png_is_accepted(mock_stream, client: TestClient) -> None:
    mock_stream.return_value = _md_gen("content")

    response = client.post(
        "/convert/?filename=scan.png",
        content=b"\x89PNG stub",
        headers=_HEADERS,
    )

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# POST /convert/text  — alias endpoint
# ---------------------------------------------------------------------------

@patch("app.routers.convert.converter.stream_to_markdown")
def test_text_endpoint_streams_plain_text(mock_stream, client: TestClient) -> None:
    mock_stream.return_value = _md_gen("# Streamed Doc\n\n", "Page 2 content\n\n")

    response = client.post(
        "/convert/text?filename=report.pdf",
        content=_PDF_BYTES,
        headers=_HEADERS,
    )

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "# Streamed Doc" in response.text
    assert "Page 2 content" in response.text


def test_text_endpoint_unsupported_extension_returns_415(client: TestClient) -> None:
    response = client.post(
        "/convert/text?filename=archive.zip",
        content=b"bytes",
        headers=_HEADERS,
    )
    assert response.status_code == 415


def test_text_endpoint_missing_filename_returns_422(client: TestClient) -> None:
    response = client.post("/convert/text", content=b"bytes", headers=_HEADERS)
    assert response.status_code == 422


def test_text_endpoint_file_too_large_returns_413(client: TestClient) -> None:
    from app.config import settings

    oversized = b"x" * (settings.max_file_size_mb * 1024 * 1024 + 1)
    response = client.post(
        "/convert/text?filename=big.pdf",
        content=oversized,
        headers=_HEADERS,
    )
    assert response.status_code == 413
