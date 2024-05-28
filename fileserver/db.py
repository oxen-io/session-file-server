from . import config
from .postfork import postfork
from .web import app

from flask import g
from psycopg_pool import ConnectionPool
from werkzeug.local import LocalProxy


psql_pool = None
slave_pool = None

@postfork
def pg_connect():
    global psql_pool, slave_pool

    # Test suite sets this to handle the connection itself:
    if 'defer' in config.pgsql_connect_opts:
        return

    conninfo = config.pgsql_connect_opts.pop('conninfo', '')
    psql_pool = ConnectionPool(
        conninfo, min_size=2, max_size=32, kwargs={**config.pgsql_connect_opts, "autocommit": True}
    )
    psql_pool.wait()

    if config.pgsql_slave is not None:
        slaveconn = config.pgsql_slave.pop('conninfo', '')
        slave_pool = ConnectionPool(
                slaveconn, min_size=2, max_size=32, kwargs={**config.pgsql_slave, "autocommit": True}
        )
        slave_pool.wait()


def get_psql_conn():
    global psql_pool
    if "psql" not in g:
        g.psql = psql_pool.getconn()

    return g.psql

def get_slave_conn():
    global slave_pool
    if "pg_slave" not in g:
        g.pg_slave = slave_pool.getconn() if slave_pool is not None else None

    return g.pg_slave


@app.teardown_appcontext
def release_psql_conn(exception):
    psql = g.pop("psql", None)
    slave = g.pop("pg_slave", None)

    if psql is not None:
        psql_pool.putconn(psql)
    if slave is not None:
        slave_pool.putconn(slave)


psql = LocalProxy(get_psql_conn)
slave = LocalProxy(get_slave_conn)
