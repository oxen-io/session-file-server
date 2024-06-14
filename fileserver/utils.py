from typing import Tuple
import base64


def bencode_consume_string(body: memoryview) -> Tuple[memoryview, memoryview]:
    """
    Parses a bencoded byte string from the beginning of `body`.  Returns a pair of memoryviews on
    success: the first is the string byte data; the second is the remaining data (i.e. after the
    consumed string).
    Raises ValueError on parse failure.
    """
    pos = 0
    while pos < len(body) and 0x30 <= body[pos] <= 0x39:  # 1+ digits
        pos += 1
    if pos == 0 or pos >= len(body) or body[pos] != 0x3A:  # 0x3a == ':'
        raise ValueError("Invalid string bencoding: did not find `N:` length prefix")

    strlen = int(body[0:pos])  # parse the digits as a base-10 integer
    pos += 1  # skip the colon
    if pos + strlen > len(body):
        raise ValueError("Invalid string bencoding: length exceeds buffer")
    return body[pos : pos + strlen], body[pos + strlen :]


def encode_base64(data: bytes):
    return base64.b64encode(data).decode()


def decode_base64(b64: str):
    """Decodes a base64 value with or without padding."""
    # Accept unpadded base64 by appending padding; b64decode won't accept it otherwise
    if 2 <= len(b64) % 4 <= 3 and not b64.endswith('='):
        b64 += '=' * (4 - len(b64) % 4)
    return base64.b64decode(b64, validate=True)

def decode_hex_or_b64(data: bytes, size: int):
    """
    Decodes hex or base64-encoded input of a binary value of size `size`.  Returns None if data is
    None; otherwise the bytes value, if parsing is successful.  Throws on invalid data.

    (Size is required because many hex strings are valid base64 and vice versa.)
    """
    if data is None:
        return None

    if len(data) == size * 2:
        return bytes.fromhex(data)

    b64_size = (size + 2) // 3 * 4  # bytes*4/3, rounded up to the next multiple of 4.
    b64_unpadded = (size * 4 + 2) // 3

    # Allow unpadded data; python's base64 has no ability to load an unpadded value, though, so pad
    # it ourselves:
    if b64_unpadded <= len(data) <= b64_size:
        decoded = decode_base64(data)
        if len(decoded) == size:  # Might not equal our target size because of padding
            return decoded

    raise ValueError("Invalid value: could not decode as hex or base64")
