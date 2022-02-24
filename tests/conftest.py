import pytest
import os

from fileserver import config

config.pgsql_connect_opts = {"defer": True}

from fileserver import web  # noqa: E402


def pytest_addoption(parser):
    parser.addoption(
        "--pgsql",
        type=str,
        help='Use the given postgresql database connect string for testing.  '
        'E.g. "dbname=test user=joe" or "postgresql://..."',
        required=True,
    )
    parser.addoption(
        "--no-drop-schema",
        action="store_true",
        default=False,
        help="Don't clean up the final test schema; typically used with --maxfail=1",
    )


@pytest.fixture(scope="session")
def db_conn(request):
    from fileserver import db as db_

    pgsql = request.config.getoption("--pgsql")
    web.app.logger.warning(f"using postgresql {pgsql}")

    config.pgsql_connect_opts = {"conninfo": pgsql}
    db_.pg_connect()
    db_.psql = db_.psql_pool.getconn()

    yield db_.psql

    web.app.logger.warning("closing db")
    if not request.config.getoption("--no-drop-schema"):
        web.app.logger.warning("DROPPING SCHEMA")
        with db_.psql.cursor() as cur:
            cur.execute("DROP SCHEMA sfs_tests CASCADE")


@pytest.fixture(autouse=True)
def db(request, db_conn):
    """
    Import this fixture to get a wiped, re-initialized database for db.engine.  The actual fixture
    value is the db module itself (so typically you don't import it at all but instead get it
    through this fixture, which also creates an empty db for you).
    """

    with db_conn.transaction(), db_conn.cursor() as cur, open(
        os.path.dirname(__file__) + "/../schema.pgsql", "r"
    ) as schema:
        cur.execute("DROP SCHEMA IF EXISTS sfs_tests CASCADE")
        cur.execute("CREATE SCHEMA IF NOT EXISTS sfs_tests")
        cur.execute("SET search_path TO sfs_tests")
        cur.execute(schema.read())

    return db_conn


@pytest.fixture
def client():
    """Yields an flask test client for the app that can be used to make test requests"""

    with web.app.test_client() as client:
        yield client
