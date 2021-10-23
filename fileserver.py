#!/usr/bin/env python3

import flask
from flask import request, g
import base64
import coloredlogs
from hashlib import blake2b
import json
import logging
import psycopg
from psycopg_pool import ConnectionPool
import requests
import secrets
from werkzeug.local import LocalProxy

import config
from timer import timer

# error status codes:
HTTP_ERROR_PAYLOAD_TOO_LARGE = 413
HTTP_ERROR_INSUFFICIENT_STORAGE = 507
HTTP_ERROR_INTERNAL_SERVER_ERROR = 500
HTTP_BAD_GATEWAY = 502
HTTP_BAD_REQUEST = 400
HTTP_NOT_FOUND = 404


if config.BACKWARDS_COMPAT_IDS:
    assert all(x in (0, 1) for x in config.BACKWARDS_COMPAT_IDS_FIXED_BITS)
    BACKWARDS_COMPAT_MSB = sum(
            y << x for x, y in enumerate(reversed(config.BACKWARDS_COMPAT_IDS_FIXED_BITS)))
    BACKWARDS_COMPAT_RANDOM_BITS = 53 - len(config.BACKWARDS_COMPAT_IDS_FIXED_BITS)

app = flask.Flask(__name__)

psql_pool = ConnectionPool(min_size=2, max_size=32, kwargs={**config.pgsql_connect_opts, "autocommit": True})

coloredlogs.install(level=config.log_level, milliseconds=True, isatty=True)


def get_psql_conn():
    if 'psql' not in g:
        g.psql = psql_pool.getconn()

    return g.psql


@app.teardown_appcontext
def release_psql_conn(exception):
    psql = g.pop('psql', None)

    if psql is not None:
        psql_pool.putconn(psql)


psql = LocalProxy(get_psql_conn)


@timer(15)
def periodic(signum):
    with app.app_context(), psql, psql.cursor() as cur:
        cur.execute("DELETE FROM files WHERE expiry <= NOW()")
        psql.commit()

        # NB: we do this infrequently (once every 30 minutes, per project) because Github rate
        # limits if you make more than 60 requests in an hour.
        # Limit to 1 because, if there are more than 1 outdated, it doesn't hurt anything to delay
        # the next one by 30 seconds (and avoids triggering github rate limiting).
        cur.execute("""
                SELECT project, version FROM release_versions
                WHERE updated < NOW() + '30 minutes ago' LIMIT 1""")
        row = cur.fetchone()
        if row:
            project, old_v = row
            v = requests.get(
                    'https://api.github.com/repos/{}/releases/latest'.format(project),
                    timeout=5
            ).json()['tag_name']
            if v != old_v:
                logging.info("{} latest release version changed from {} to {}".format(
                    project, old_v, v))
            cur.execute("""
                UPDATE release_versions SET updated = NOW(), version = %s
                WHERE project = %s""", (v, project))


def error_resp(code):
    """
    Simple JSON error response to send back, embedded as `status_code` and also as the HTTP response
    code.
    """
    return flask.Response(
            json.dumps({'status_code': code}),
            status=code,
            mimetype='application/json')


def generate_file_id(data):
    """
    Generate a file ID by blake2b hashing the file body, then using a 33-byte digest encoded into 44
    base64 chars.  (Ideally would be 32, but that would result in base64 padding, so increased to 33
    to fit perfectly).
    """
    return base64.urlsafe_b64encode(
            blake2b(data, digest_size=33, salt=b'SessionFileSvr\0\0').digest()).decode()


@app.route('/file', methods=['POST'])
def submit_file(*, body=None, deprecated=False):
    if body is None:
        body = request.data

    if not 0 < len(body) <= config.MAX_FILE_SIZE:
        logging.warn("Rejecting upload of size {} ∉ (0, {}]".format(
            len(body), config.MAX_FILE_SIZE))
        return error_resp(HTTP_ERROR_PAYLOAD_TOO_LARGE)

    id = None
    try:
        if config.BACKWARDS_COMPAT_IDS:
            done = False
            for attempt in range(25):

                id = (BACKWARDS_COMPAT_MSB << BACKWARDS_COMPAT_RANDOM_BITS
                      | secrets.randbits(BACKWARDS_COMPAT_RANDOM_BITS))
                if not deprecated:
                    id = str(id)  # New ids are always strings; legacy requests require an integer
                try:
                    with psql.cursor() as cur:
                        cur.execute(
                            "INSERT INTO files (id, data, expiry) VALUES (%s, %s, NOW() + %s)",
                            (id, body, config.FILE_EXPIRY))
                except psycopg.errors.UniqueViolation:
                    continue
                done = True
                break

            if not done:
                logging.error(
                    "Tried 25 random IDs and got all constraint failures, something getting wrong!")
                return error_resp(HTTP_ERROR_INSUFFICIENT_STORAGE)

        else:
            with psql.transaction(), psql.cursor() as cur:
                id = generate_file_id(body)
                try:
                    # Don't pass the data yet because we might be de-duplicating
                    with psql.transaction():
                        cur.execute(
                                "INSERT INTO files (id, data, expiry) VALUES (%s, '', NOW() + %s)",
                                (id, config.FILE_EXPIRY))
                except psycopg.errors.UniqueViolation:
                    # Found a duplicate id, so de-duplicate by just refreshing the expiry
                    cur.execute(
                            "UPDATE files SET uploaded = NOW(), expiry = NOW() + %s WHERE id = %s",
                            (config.FILE_EXPIRY, id))
                else:
                    cur.execute("UPDATE files SET data = %s WHERE id = %s", (body, id))

    except Exception as e:
        logging.error("Failed to insert file: {}".format(e))
        return error_resp(HTTP_ERROR_INTERNAL_SERVER_ERROR)

    response = {"id": id}
    if deprecated:
        response['status_code'] = 200
    return flask.jsonify(response)


@app.route('/files', methods=['POST'])
def submit_file_old():
    input = request.json()
    if input is None or 'file' not in input:
        logging.warn("Invalid request: did not find json with a 'file' property")
        return error_resp(HTTP_BAD_REQUEST)

    body = input['file']
    if not 0 < len(body) <= config.MAX_FILE_SIZE_B64:
        logging.warn("Rejecting upload of b64-encoded size {} ∉ (0, {}]".format(
            len(body), config.MAX_FILE_SIZE_B64))
        return error_resp(HTTP_ERROR_PAYLOAD_TOO_LARGE)

    # base64.b64decode is picky about padding (but not, by default, about random non-alphabet
    # characters in the middle of the data, wtf!)
    while len(body) % 4 != 0:
        body += '='
    body = base64.b64decode(body, validate=True)

    return submit_file(body=body)


@app.route('/file/<id>')
def get_file(id):
    with psql.cursor() as cur:
        cur.execute("SELECT data FROM files WHERE id = %s", (id,), binary=True)
        row = cur.fetchone()
        if row:
            response = flask.make_response(row[0].tobytes())
            response.headers.set('Content-Type', 'application/octet-stream')
            return response
        else:
            logging.warn("File '{}' does not exist".format(id))
            return error_resp(HTTP_NOT_FOUND)


@app.route('/files/<id>')
def get_file_old(id):
    with psql.cursor() as cur:
        cur.execute("SELECT data FROM files WHERE id = %s", (id,), binary=True)
        row = cur.fetchone()
        if row:
            return flask.jsonify({
                "status_code": 200,
                "result": base64.b64encode(row[0])
                })
        else:
            logging.warn("File '{}' does not exist".format(id))
            return error_resp(HTTP_NOT_FOUND)


@app.route('/file/<id>/info')
def get_file_info(id):
    with psql.cursor() as cur:
        cur.execute("SELECT length(data), uploaded, expiry FROM files WHERE id = %s", (id,))
        row = cur.fetchone()
        if row:
            return flask.jsonify({
                "size": row[0],
                "uploaded": row[1].timestamp(),
                "expires": row[2].timestamp()
                })
        else:
            logging.warn("File '{}' does not exist".format(id))
            return error_resp(HTTP_NOT_FOUND)


@app.route('/session_version')
def get_session_version():
    platform = request.args['platform']

    if platform not in ('desktop', 'android', 'ios'):
        logging.warn("Invalid session platform '{}'".format(platform))
        return error_resp(HTTP_NOT_FOUND)
    project = 'oxen-io/session-' + platform

    with psql.cursor() as cur:
        cur.execute("""
            SELECT version, updated FROM release_versions
            WHERE project = %s AND updated >= NOW() + '24 hours ago'
        """, (project,))
        row = cur.fetchone()
        if row is None:
            logging.warn("{} version is more than 24 hours stale!".format(project))
            return error_resp(HTTP_BAD_GATEWAY)
        return flask.jsonify({
            "status_code": 200,
            "updated": row[1].timestamp(),
            "result": row[0]
            })
