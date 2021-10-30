#!/usr/bin/env python3

import flask
from flask import request, g

from datetime import datetime
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
import io
import os
import nacl.public
import pyonionreq.junk

import config
from timer import timer
from postfork import postfork
from stats import log_stats

# error status codes:
HTTP_ERROR_PAYLOAD_TOO_LARGE = 413
HTTP_ERROR_INSUFFICIENT_STORAGE = 507
HTTP_ERROR_INTERNAL_SERVER_ERROR = 500
HTTP_BAD_GATEWAY = 502
HTTP_BAD_REQUEST = 400
HTTP_NOT_FOUND = 404

coloredlogs.install(level=config.log_level, milliseconds=True, isatty=True)

if config.BACKWARDS_COMPAT_IDS:
    assert all(x in (0, 1) for x in config.BACKWARDS_COMPAT_IDS_FIXED_BITS)
    BACKWARDS_COMPAT_MSB = sum(
            y << x for x, y in enumerate(reversed(config.BACKWARDS_COMPAT_IDS_FIXED_BITS)))
    BACKWARDS_COMPAT_RANDOM_BITS = 53 - len(config.BACKWARDS_COMPAT_IDS_FIXED_BITS)

if os.path.exists('key_x25519'):
    with open('key_x25519', 'rb') as f:
        key = f.read()
        if len(key) != 32:
            raise RuntimeError("Invalid key_x25519: expected 32 bytes, not {} bytes".format(len(key)))
    privkey = nacl.public.PrivateKey(key)
else:
    privkey = nacl.public.PrivateKey.generate()
    with open('key_x25519', 'wb') as f:
        f.write(privkey.encode())

logging.info("File server pubkey: {}".format(
    privkey.public_key.encode(encoder=nacl.encoding.HexEncoder).decode()))

onionparser = pyonionreq.junk.Parser(pubkey=privkey.public_key.encode(), privkey=privkey.encode())

app = flask.Flask(__name__)


@postfork
def pg_connect():
    global psql_pool
    psql_pool = ConnectionPool(min_size=2, max_size=32, kwargs={**config.pgsql_connect_opts, "autocommit": True})
    psql_pool.wait()


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


last_stats_printed = None


@timer(15)
def periodic(signum):
    with app.app_context(), psql.cursor() as cur:
        logging.debug("Cleaning up expired files")
        cur.execute("DELETE FROM files WHERE expiry <= NOW()")

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

        now = datetime.now()
        global last_stats_printed
        if last_stats_printed is None or (now - last_stats_printed).total_seconds() >= 3600:
            print("wtf now={}, lsp={}".format(now, last_stats_printed))
            log_stats(cur)
            last_stats_printed = now


def json_resp(data, status=200):
    """Takes data and optionally an HTTP status, returns it as a json response."""
    return flask.Response(
            json.dumps(data),
            status=code,
            mimetype='application/json')


def error_resp(code):
    """
    Simple JSON error response to send back, embedded as `status_code` and also as the HTTP response
    code.
    """
    return json_resp({'status_code': code}, code)


def generate_file_id(data):
    """
    Generate a file ID by blake2b hashing the file body, then using a 33-byte digest encoded into 44
    base64 chars.  (Ideally would be 32, but that would result in base64 padding, so increased to 33
    to fit perfectly).
    """
    return base64.urlsafe_b64encode(
            blake2b(data, digest_size=33, salt=b'SessionFileSvr\0\0').digest()).decode()


@app.post('/file')
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
    return json_resp(response)


@app.post('/files')
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
            return json_resp({
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
            return json_resp({
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
        return json_resp({
            "status_code": 200,
            "updated": row[1].timestamp(),
            "result": row[0]
            })


# FIXME TODO: this has some other allowed aliases, I think, /oxen and... dunno?  Check SS.
@app.post('/loki/v3/lsrpc')
def onion_request():
    body = request.data

    logging.warn("onion request received: {}".format(body))

    try:
        junk = onionparser.parse_junk(body)
    except RuntimeError as e:
        logging.warn("Failed to decrypt onion request: {}".format(e))
        return flask.Response(status=HTTP_ERROR_INTERNAL_SERVER_ERROR)

    body = junk.payload
    logging.warn("onion request decrypted to: {}".format(body))
    try:
        if body.startswith(b'{'):
            # JSON input
            req = json.loads(body)
            meth, target = req['method'], req['endpoint']
            if '?' in target:
                target, query_string = target.split('?', 1)
            else:
                query_string = ''

            subreq_body = body.get('body', '').encode()
            if meth in ('POST', 'PUT'):
                ct = body.get('contentType', 'application/json')
                cl = len(subreq_body)
            else:
                if 'body' in req and len(req['body']):
                    raise RuntimeError("Invalid {} {} request: request must not contain a body", meth, target)
                ct, cl = '', ''
        elif body.startswith(b'd'):
            # bt-encoded input
            raise RuntimeError("Not implemented yet")

        else:
            raise RuntimeError("Invalid onion request body: expected JSON object or a bt-encoded dict")

        # Set up the wsgi environ variables for the subrequest (see PEP 0333)
        subreq_env = {
                **request.environ,
                "REQUEST_METHOD": method,
                "PATH_INFO": target,
                "QUERY_STRING": query_string,
                "CONTENT_TYPE": ct,
                "CONTENT_LENGTH": cl,
                **{'HTTP_{}'.format(h.upper().replace('-', '_')): v for h, v in req.get('headers', {}).items()},
                'wsgi.input': input
                }

        try:
            with app.request_context(subreq_env) as subreq_ctx:
                response = app.full_dispatch_request()
            return junk.transformReply(response.get_data())

        except Exception as e:
            logging.warn("Onion sub-request failed: {}".format(e))
            return flask.Response(status=HTTP_BAD_GATEWAY)

    except Exception as e:
        logging.warn("Invalid onion request: {}".format(e))
        return error_resp(HTTP_ERROR_INTERNAL_SERVER_ERROR)
