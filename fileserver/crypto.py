import nacl.public
import os

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

app.logger.info(
    "File server pubkey: {}".format(
        privkey.public_key.encode(encoder=nacl.encoding.HexEncoder).decode()
    )
)
