from .web import app
from . import db
from .timer import timer
from .stats import log_stats

from datetime import datetime
import requests

last_stats_printed = None


@timer(15)
def periodic(signum):
    with app.app_context(), db.psql.cursor() as cur:
        app.logger.debug("Cleaning up expired files")
        cur.execute("DELETE FROM files WHERE expiry <= NOW()")

        # NB: we do this infrequently (once every 30 minutes, per project) because Github rate
        # limits if you make more than 60 requests in an hour.
        # Limit to 1 because, if there are more than 1 outdated, it doesn't hurt anything to delay
        # the next one by 30 seconds (and avoids triggering github rate limiting).
        cur.execute(
            """
            SELECT project, version FROM release_versions
            WHERE updated < NOW() + '30 minutes ago' LIMIT 1
            """
        )
        row = cur.fetchone()
        if row:
            project, old_v = row
            v = requests.get(
                "https://api.github.com/repos/{}/releases/latest".format(project), timeout=5
            ).json()["tag_name"]
            if v != old_v:
                app.logger.info(
                    "{} latest release version changed from {} to {}".format(project, old_v, v)
                )
            cur.execute(
                """
                UPDATE release_versions SET updated = NOW(), version = %s
                WHERE project = %s""",
                (v, project),
            )

        now = datetime.now()
        global last_stats_printed
        if last_stats_printed is None or (now - last_stats_printed).total_seconds() >= 3600:
            log_stats(cur)
            last_stats_printed = now
