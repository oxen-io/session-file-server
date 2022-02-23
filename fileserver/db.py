from . import config
from .postfork import postfork
from .web import app

from flask import g
from psycopg_pool import ConnectionPool
from werkzeug.local import LocalProxy


@postfork
def pg_connect():
    global psql_pool

    # Test suite sets this to handle the connection itself:
    if 'defer' in config.pgsql_connect_opts:
        return

    conninfo = config.pgsql_connect_opts.pop('conninfo', '')
    psql_pool = ConnectionPool(
        conninfo, min_size=2, max_size=32, kwargs={**config.pgsql_connect_opts, "autocommit": True}
    )
    psql_pool.wait()


def get_psql_conn():
    if "psql" not in g:
        g.psql = psql_pool.getconn()

    return g.psql


@app.teardown_appcontext
def release_psql_conn(exception):
    psql = g.pop("psql", None)

    if psql is not None:
        psql_pool.putconn(psql)


psql = LocalProxy(get_psql_conn)
