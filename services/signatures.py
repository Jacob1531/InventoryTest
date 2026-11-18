"""
signatures.py
=====================================================================
Validation for hand-drawn e-signatures.

The signature pad in Account Settings draws on an HTML canvas and
posts it as a PNG data URL ("data:image/png;base64,..."). Everything
the browser sends is untrusted, so before anything is stored this
checks that it really is a PNG of sensible size and dimensions, and
not something else wearing a PNG label.

The image goes in the database rather than Blob Storage. A signature
is a few KB, and keeping it in a row means a future "signed on
delivery" record can copy the exact image it was signed with, so
replacing your signature later never changes what was already signed.

Pure and DB-independent so it can be unit tested.
=====================================================================
"""
import base64
import binascii
import struct

DATA_URL_PREFIX = "data:image/png;base64,"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# A drawn signature on a ~600x200 canvas is usually 5-30 KB. The cap
# leaves plenty of headroom for high-DPI screens while refusing anything
# that clearly isn't a signature.
MAX_BYTES = 300 * 1024
MAX_WIDTH = 2400
MAX_HEIGHT = 1000
MIN_WIDTH = 50
MIN_HEIGHT = 20


class SignatureError(ValueError):
    """Raised with a message that is safe to show the user."""


def png_dimensions(data):
    """Width and height from a PNG's IHDR chunk, without needing an
    image library. The IHDR is always the first chunk: 8-byte magic,
    4-byte length, 'IHDR', then width and height as big-endian ints."""
    if len(data) < 24 or not data.startswith(PNG_MAGIC) or data[12:16] != b"IHDR":
        raise SignatureError("The signature isn't a valid image.")
    return struct.unpack(">II", data[16:24])


def decode_signature(data_url):
    """Turns the posted data URL into validated PNG bytes.

    Raises SignatureError with a user-facing message if anything is off."""
    if not data_url or not isinstance(data_url, str):
        raise SignatureError("Draw your signature before saving.")

    data_url = data_url.strip()
    if not data_url.startswith(DATA_URL_PREFIX):
        raise SignatureError("The signature isn't a valid image.")

    encoded = data_url[len(DATA_URL_PREFIX):]
    # Base64 is ~4/3 the size of the bytes it holds; reject oversized
    # input before decoding it.
    if len(encoded) > MAX_BYTES * 4 // 3 + 4:
        raise SignatureError("The signature image is too large.")

    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise SignatureError("The signature isn't a valid image.")

    if len(data) > MAX_BYTES:
        raise SignatureError("The signature image is too large.")

    width, height = png_dimensions(data)
    if width < MIN_WIDTH or height < MIN_HEIGHT:
        raise SignatureError("The signature image is too small.")
    if width > MAX_WIDTH or height > MAX_HEIGHT:
        raise SignatureError("The signature image is too large.")

    return data
