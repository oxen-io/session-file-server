import nacl.public
import os
import pyonionreq.junk

from .web import app

if os.path.exists("key_x25519"):
    with open("key_x25519", "rb") as f:
        key = f.read()
        if len(key) != 32:
            raise RuntimeError(
                "Invalid key_x25519: expected 32 bytes, not {} bytes".format(len(key))
            )
    privkey = nacl.public.PrivateKey(key)
else:
    privkey = nacl.public.PrivateKey.generate()
    with open("key_x25519", "wb") as f:
        f.write(privkey.encode())

_junk_parser = pyonionreq.junk.Parser(privkey=privkey.encode(), pubkey=privkey.public_key.encode())
parse_junk = _junk_parser.parse_junk

app.logger.info(
    "File server pubkey: {}".format(
        privkey.public_key.encode(encoder=nacl.encoding.HexEncoder).decode()
    )
)
