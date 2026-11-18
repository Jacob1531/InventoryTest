"""
Tests for services/signatures.py - validating hand-drawn signature
images posted from the Account Settings signature pad.

Run with: pytest tests/test_signatures.py
"""
import base64
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from services.signatures import (MAX_BYTES, SignatureError, decode_signature,
                                 png_dimensions)


def _png(width, height):
    """A real, minimal transparent PNG of the given size."""
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x00" * (width * 4) for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _url(data):
    return "data:image/png;base64," + base64.b64encode(data).decode()


def test_accepts_a_normal_signature():
    png = _png(400, 120)
    assert decode_signature(_url(png)) == png


def test_reads_dimensions_from_the_header():
    assert png_dimensions(_png(321, 77)) == (321, 77)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_rejects_an_empty_submission(value):
    with pytest.raises(SignatureError):
        decode_signature(value)


def test_rejects_other_image_types():
    """Only PNG is accepted - the pad always produces PNG."""
    with pytest.raises(SignatureError):
        decode_signature("data:image/jpeg;base64," + base64.b64encode(b"x" * 100).decode())


def test_rejects_svg_or_html_disguised_as_png():
    """Content that isn't really a PNG is refused even with a PNG label."""
    with pytest.raises(SignatureError):
        decode_signature(_url(b"<svg onload=alert(1)></svg>" + b" " * 40))


def test_rejects_invalid_base64():
    with pytest.raises(SignatureError):
        decode_signature("data:image/png;base64,not!!valid@@base64")


def test_rejects_images_that_are_too_small():
    with pytest.raises(SignatureError):
        decode_signature(_url(_png(10, 5)))


def test_rejects_images_that_are_too_wide_or_tall():
    with pytest.raises(SignatureError):
        decode_signature(_url(_png(5000, 100)))
    with pytest.raises(SignatureError):
        decode_signature(_url(_png(400, 3000)))


def test_rejects_files_over_the_size_cap():
    big = _png(400, 120) + b"\x00" * (MAX_BYTES + 1)
    with pytest.raises(SignatureError):
        decode_signature(_url(big))


def test_error_messages_are_user_friendly():
    try:
        decode_signature("")
    except SignatureError as e:
        assert "signature" in str(e).lower()
