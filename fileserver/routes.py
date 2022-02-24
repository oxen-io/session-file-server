from . import config
from .web import app
from . import db
from . import http, utils

import flask
from flask import request
import secrets
from base64 import urlsafe_b64encode
from hashlib import blake2b
import json
import psycopg

if config.BACKWARDS_COMPAT_IDS:
    assert all(x in (0, 1) for x in config.BACKWARDS_COMPAT_IDS_FIXED_BITS)
    BACKWARDS_COMPAT_MSB = sum(
        y << x for x, y in enumerate(reversed(config.BACKWARDS_COMPAT_IDS_FIXED_BITS))
    )
    BACKWARDS_COMPAT_RANDOM_BITS = 53 - len(config.BACKWARDS_COMPAT_IDS_FIXED_BITS)


def json_resp(data, status=200):
    """Takes data and optionally an HTTP status, returns it as a json response."""
    return flask.Response(json.dumps(data), status=status, mimetype="application/json")


def error_resp(code):
    """
    Simple JSON error response to send back, embedded as `status_code` and also as the HTTP response
    code.
    """
    return json_resp({"status_code": code}, code)


def generate_file_id(data):
    """
    Generate a file ID by blake2b hashing the file body, then using a 33-byte digest encoded into 44
    base64 chars.  (Ideally would be 32, but that would result in base64 padding, so increased to 33
    to fit perfectly).
    """
    return urlsafe_b64encode(
        blake2b(data, digest_size=33, salt=b"SessionFileSvr\0\0").digest()
    ).decode()


@app.post("/file")
def submit_file(*, body=None, deprecated=False):
    if body is None:
        body = request.data

    if not 0 < len(body) <= config.MAX_FILE_SIZE:
        app.logger.warn(
            "Rejecting upload of size {} ∉ (0, {}]".format(len(body), config.MAX_FILE_SIZE)
        )
        return error_resp(http.PAYLOAD_TOO_LARGE)

    id = None
    try:
        if config.BACKWARDS_COMPAT_IDS:
            done = False
            for attempt in range(25):

                id = BACKWARDS_COMPAT_MSB << BACKWARDS_COMPAT_RANDOM_BITS | secrets.randbits(
                    BACKWARDS_COMPAT_RANDOM_BITS
                )
                if not deprecated:
                    id = str(id)  # New ids are always strings; legacy requests require an integer
                try:
                    with db.psql.cursor() as cur:
                        cur.execute(
                            "INSERT INTO files (id, data, expiry) VALUES (%s, %s, NOW() + %s)",
                            (id, body, config.FILE_EXPIRY),
                        )
                except psycopg.errors.UniqueViolation:
                    continue
                done = True
                break

            if not done:
                app.logger.error(
                    "Tried 25 random IDs and got all constraint failures, something getting wrong!"
                )
                return error_resp(http.INSUFFICIENT_STORAGE)

        else:
            with db.psql.transaction(), db.psql.cursor() as cur:
                id = generate_file_id(body)
                try:
                    # Don't pass the data yet because we might be de-duplicating
                    with db.psql.transaction():
                        cur.execute(
                            "INSERT INTO files (id, data, expiry) VALUES (%s, '', NOW() + %s)",
                            (id, config.FILE_EXPIRY),
                        )
                except psycopg.errors.UniqueViolation:
                    # Found a duplicate id, so de-duplicate by just refreshing the expiry
                    cur.execute(
                        "UPDATE files SET uploaded = NOW(), expiry = NOW() + %s WHERE id = %s",
                        (config.FILE_EXPIRY, id),
                    )
                else:
                    cur.execute("UPDATE files SET data = %s WHERE id = %s", (body, id))

    except Exception as e:
        app.logger.error("Failed to insert file: {}".format(e))
        return error_resp(http.INTERNAL_SERVER_ERROR)

    response = {"result": id, "status_code": 200} if deprecated else {"id": id}
    return json_resp(response)


@app.post("/files")
def submit_file_old():
    input = request.json
    if input is None or "file" not in input:
        app.logger.warn("Invalid request: did not find json with a 'file' property")
        return error_resp(http.BAD_REQUEST)

    body = input["file"]
    if not 0 < len(body) <= config.MAX_FILE_SIZE_B64:
        app.logger.warn(
            "Rejecting upload of b64-encoded size {} ∉ (0, {}]".format(
                len(body), config.MAX_FILE_SIZE_B64
            )
        )
        return error_resp(http.PAYLOAD_TOO_LARGE)

    body = utils.decode_base64(body)

    return submit_file(body=body, deprecated=True)


@app.get("/file/<id>")
def get_file(id):
    with db.psql.cursor() as cur:
        cur.execute("SELECT data FROM files WHERE id = %s", (id,), binary=True)
        row = cur.fetchone()
        if row:
            response = flask.make_response(row[0].tobytes())
            response.headers.set("Content-Type", "application/octet-stream")
            return response
        else:
            app.logger.warn("File '{}' does not exist".format(id))
            return error_resp(http.NOT_FOUND)


@app.get("/files/<id>")
def get_file_old(id):
    with db.psql.cursor() as cur:
        cur.execute("SELECT data FROM files WHERE id = %s", (id,), binary=True)
        row = cur.fetchone()
        if row:
            return json_resp({"status_code": 200, "result": utils.encode_base64(row[0])})
        else:
            app.logger.warn("File '{}' does not exist".format(id))
            return error_resp(http.NOT_FOUND)


@app.get("/file/<id>/info")
def get_file_info(id):
    with db.psql.cursor() as cur:
        cur.execute("SELECT length(data), uploaded, expiry FROM files WHERE id = %s", (id,))
        row = cur.fetchone()
        if row:
            return json_resp(
                {"size": row[0], "uploaded": row[1].timestamp(), "expires": row[2].timestamp()}
            )
        else:
            app.logger.warn("File '{}' does not exist".format(id))
            return error_resp(http.NOT_FOUND)


@app.get("/session_version")
def get_session_version():
    platform = request.args.get("platform")

    if platform not in ("desktop", "android", "ios"):
        app.logger.warn("Invalid session platform '{}'".format(platform))
        return error_resp(http.NOT_FOUND)
    project = "oxen-io/session-" + platform

    with db.psql.cursor() as cur:
        cur.execute(
            """
            SELECT version, updated FROM release_versions
            WHERE project = %s AND updated >= NOW() + '24 hours ago'
        """,
            (project,),
        )
        row = cur.fetchone()
        if row is None:
            app.logger.warn("{} version is more than 24 hours stale!".format(project))
            return error_resp(http.BAD_GATEWAY)
        return json_resp({"status_code": 200, "updated": row[1].timestamp(), "result": row[0]})
