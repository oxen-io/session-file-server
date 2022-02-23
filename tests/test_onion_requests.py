from fileserver.web import app
from fileserver import crypto, db, utils
from nacl.bindings import (
    crypto_scalarmult,
    crypto_aead_xchacha20poly1305_ietf_encrypt,
    crypto_aead_xchacha20poly1305_ietf_decrypt,
)
from Cryptodome.Cipher import AES
import nacl.utils
import nacl.hashlib
import struct
import json
import time

from nacl.public import PrivateKey

# ephemeral X25519 keypair for use in tests
a = PrivateKey(bytes.fromhex('ec32fb5766cf52b1b5d7b0bff08e29f5c0c58ca19beaf6a5c7d3dd8ac7ced963'))
A = a.public_key
assert A.encode().hex() == 'd79a50b82ba8ca665f854382b42ba159efd16eef87409e97a8d07395b9492928'

# For xchacha20 we use the libsodium recommended shared key of H(aB || A || B), where H(.) is
# 32-byte Blake2B
shared_xchacha20_key = nacl.hashlib.blake2b(
    crypto_scalarmult(a.encode(), crypto.privkey.public_key.encode())
    + A.encode()
    + crypto.privkey.public_key.encode(),
    digest_size=32,
).digest()

# AES-GCM onion requests were implemented using the somewhat weaker shared key of just aB:
shared_aes_key = crypto_scalarmult(a.encode(), crypto.privkey.public_key.encode())


def build_payload(inner_json, inner_body=None, *, v, enc_type, outer_json_extra={}):
    """Encrypt and encode a payload for fileserver"""

    if not isinstance(inner_json, bytes):
        inner_json = json.dumps(inner_json).encode()

    if v == 3:
        assert inner_body is None
        inner_data = inner_json
    elif v == 4:
        inner_data = b''.join(
            (
                b'l',
                str(len(inner_json)).encode(),
                b':',
                inner_json,
                *(() if inner_body is None else (str(len(inner_body)).encode(), b':', inner_body)),
                b'e',
            )
        )
    else:
        raise RuntimeError(f"invalid payload v{v}")

    inner_enc = ()
    if enc_type in ("xchacha20", "xchacha20-poly1305"):
        # For xchacha20 we stick the nonce to the beginning of the encrypted blob
        nonce = nacl.utils.random(24)
        inner_enc = (
            nonce,
            crypto_aead_xchacha20poly1305_ietf_encrypt(
                inner_data, aad=None, nonce=nonce, key=shared_xchacha20_key
            ),
        )
    elif enc_type in ("aes-gcm", "gcm"):
        # For aes-gcm we stick the iv on the beginning of the encrypted blob and the mac tag on the
        # end of it
        iv = nacl.utils.random(12)
        cipher = AES.new(shared_aes_key, AES.MODE_GCM, iv)
        enc, mac = cipher.encrypt_and_digest(inner_data)
        inner_enc = (iv, enc, mac)
    else:
        raise ValueError(f"Invalid enc_type: {enc_type}")

    # The outer request is in storage server onion request format:
    # [N][junk]{json}
    # where we load the fields for the last hop *and* the fields for fileserver into the json.
    outer_json = {
        "host": "localhost",
        "port": 80,
        "protocol": "http",
        "target": f"/oxen/v{v}/lsrpc",
        "ephemeral_key": A.encode().hex(),
        "enc_type": enc_type,
        **outer_json_extra,
    }
    return b''.join(
        (
            struct.pack('<i', sum(len(x) for x in inner_enc)),
            *inner_enc,
            json.dumps(outer_json).encode(),
        )
    )


def decrypt_reply(data, *, v, enc_type):
    """
    Parses a reply; returns the json metadata and the body.  Note for v3 that there is only json;
    body will always be None.
    """
    if v == 3:
        data = utils.decode_base64(data)

    if enc_type in ("xchacha20", "xchacha20-poly1305"):
        assert len(data) > 24
        nonce, enc = data[:24], data[24:]
        data = crypto_aead_xchacha20poly1305_ietf_decrypt(
            enc, aad=None, nonce=nonce, key=shared_xchacha20_key
        )
    elif enc_type in ("aes-gcm", "gcm"):
        assert len(data) > 28
        iv, enc, mac = data[:12], data[12:-16], data[-16:]
        cipher = AES.new(shared_aes_key, AES.MODE_GCM, iv)
        data = cipher.decrypt_and_verify(enc, mac)
    else:
        raise ValueError(f"Invalid enc_type: {enc_type}")

    body = None

    if v == 4:
        assert (data[:1], data[-1:]) == (b'l', b'e')
        data = memoryview(data)[1:-1]
        json_data, data = utils.bencode_consume_string(data)
        json_ = json.loads(json_data.tobytes())
        if data:
            body, data = utils.bencode_consume_string(data)
            assert len(data) == 0
            body = body.tobytes()
    elif v == 3:
        json_ = json.loads(data)

    return json_, body


def update_session_desktop_version():
    """
    Fileserver errors if the db update version is more than 24 hours old, so update it to a fake
    version for testing.
    """

    with db.psql.cursor() as cur:
        cur.execute(
            "UPDATE release_versions SET version = %s, updated = NOW() WHERE project = %s",
            ('v1.2.3', 'oxen-io/session-desktop'),
        )


def test_v3(client):
    update_session_desktop_version()

    # Construct an onion request for /room/test-room
    req = {'method': 'GET', 'endpoint': 'session_version?platform=desktop'}
    data = build_payload(req, v=3, enc_type="xchacha20")

    r = client.post("/loki/v3/lsrpc", data=data)

    assert r.status_code == 200

    v = decrypt_reply(r.data, v=3, enc_type="xchacha20")[0]

    assert -1 < time.time() - v.pop('updated') < 1
    assert v == {'status_code': 200, 'result': 'v1.2.3'}


def test_v4(client):
    update_session_desktop_version()

    req = {'method': 'GET', 'endpoint': '/session_version?platform=desktop'}
    data = build_payload(req, v=4, enc_type="xchacha20")

    r = client.post("/oxen/v4/lsrpc", data=data)

    assert r.status_code == 200

    info, body = decrypt_reply(r.data, v=4, enc_type="xchacha20")

    assert info == {'code': 200, 'headers': {'content-type': 'application/json'}}

    v = json.loads(body)
    assert -1 < time.time() - v.pop('updated') < 1
    assert v == {'status_code': 200, 'result': 'v1.2.3'}


@app.post("/test_v4_post_body")
def v4_post_body():
    from flask import request, jsonify, Response

    if request.json is not None:
        return jsonify({"json": request.json})
    print(f"rd: {request.data}")
    return Response(
        f"not json ({request.content_type}): {request.data.decode()}".encode(),
        mimetype='text/plain',
    )


def test_v4_post_body(client):
    req = {'method': 'POST', 'endpoint': '/test_v4_post_body'}
    content = b'test data'
    req['headers'] = {'content-type': 'text/plain'}

    data = build_payload(req, content, v=4, enc_type="xchacha20")

    r = client.post("/oxen/v4/lsrpc", data=data)

    assert r.status_code == 200

    info, body = decrypt_reply(r.data, v=4, enc_type="xchacha20")

    assert info == {'code': 200, 'headers': {'content-type': 'text/plain; charset=utf-8'}}
    assert body == b'not json (text/plain): test data'

    # Now try with json:
    test_json = {"test": ["json", None], "1": 23}
    content = json.dumps(test_json).encode()
    req['headers'] = {'content-type': 'application/json'}

    data = build_payload(req, content, v=4, enc_type="xchacha20")
    r = client.post("/oxen/v4/lsrpc", data=data)

    assert r.status_code == 200

    info, body = decrypt_reply(r.data, v=4, enc_type="xchacha20")

    assert info == {'code': 200, 'headers': {'content-type': 'application/json'}}
    assert json.loads(body) == {"json": test_json}

    # Now try with json, but with content-type set to something else (this should avoid the json
    req['headers'] = {'content-type': 'x-omg/all-your-base'}
    data = build_payload(req, content, v=4, enc_type="xchacha20")
    r = client.post("/oxen/v4/lsrpc", data=data)

    assert r.status_code == 200

    info, body = decrypt_reply(r.data, v=4, enc_type="xchacha20")

    assert info == {'code': 200, 'headers': {'content-type': 'text/plain; charset=utf-8'}}
    assert body == b'not json (x-omg/all-your-base): ' + content
