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
    print(f"body: {body.tobytes()}")
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
