from flask import current_app
from .web import app
from . import db
from . import config
from .timer import timer
from .stats import log_stats

from datetime import datetime
import requests

last_stats_printed = None

def insert_new_assets(cur, project, version, assets):
    if assets:
        for asset in assets:
            cur.execute(
                """
                INSERT INTO release_assets (project, version, name, url) VALUES (%s, %s, %s, %s)
                """,
                (project, version, asset['name'], asset['url']),
            )

@timer(15, target="worker1")
def periodic(signum):
    with app.app_context():
        for psql in (db.psql, db.slave):
            if not psql:
                continue

            with psql.cursor() as cur:
                cur.execute("DELETE FROM files WHERE expiry <= NOW()")
                if config.BACKUP_TABLE is not None:
                    cur.execute(f"DELETE FROM {config.BACKUP_TABLE} WHERE expiry <= NOW()")

                # NB: we do this infrequently (once every 30 minutes, per project) because Github rate
                # limits if you make more than 60 requests in an hour.
                # Limit to 1 because, if there are more than 1 outdated, it doesn't hurt anything to delay
                # the next one by 30 seconds (and avoids triggering github rate limiting).
                cur.execute(
                    """
                    SELECT project, version FROM release_versions
                    WHERE updated < NOW() + '30 minutes ago' AND prerelease = False LIMIT 1
                    """
                )
                row = cur.fetchone()
                if row:
                    project, old_v = row
                    latest = requests.get(
                        "https://api.github.com/repos/{}/releases/latest".format(project), timeout=5
                    ).json()

                    # If the latest release doesn't have version information then don't bother continuing
                    # this means something is invalid, or we were rate limited
                    if 'tag_name' not in latest:
                        app.logger.warn(f"'tag_name' key not found in latest release for project {project}")
                        continue

                    recent = requests.get(
                        "https://api.github.com/repos/{}/releases?per_page=3".format(project), timeout=5
                    ).json()

                    v = latest["tag_name"]
                    if v != old_v:
                        app.logger.info(
                            "{} latest release version changed from {} to {}".format(project, old_v, v)
                        )
                    cur.execute(
                        """
                        UPDATE release_versions SET updated = NOW(), version = %s, name = %s, notes = %s
                        WHERE project = %s""",
                        (v, project, latest['name'], latest['body']),
                    )

                    # Remove any old assets and prereleases
                    prerelease = next((r for r in recent if r['prerelease']), None)
                    old_prerelease_v = None

                    if prerelease is not None:
                        cur.execute(
                            """
                            SELECT version FROM release_versions
                            WHERE project = %s AND prerelease = True LIMIT 1""",
                            (project),
                        )

                        prerow = cur.fetchone()
                        if prerow:
                            old_prerelease_v = prerow

                    if v != old_v or (prerelease and prerelease['tag_name'] != old_prerelease_v):
                        cur.execute(
                            """
                            DELETE FROM release_assets
                            WHERE project = %s""",
                            (project,),
                        )
                        cur.execute(
                            """
                            DELETE FROM release_versions
                            WHERE project = %s AND prerelease = True""",
                            (project,),
                        )

                        # Insert new assets
                        insert_new_assets(cur, project, v, latest['assets'])

                        # Add new prereleases
                        if prerelease:
                            cur.execute(
                                """
                                INSERT INTO release_versions (project, version, prerelease, name, nodes, updated) VALUES (%s, %s, True, %s, %s, NOW())
                                """,
                                (project, prerelease['tag_name'], asset['name'], asset['url']),
                            )
                            insert_new_assets(cur, project, prerelease['tag_name'], prerelease['assets'])

                now = datetime.now()
                global last_stats_printed
                if last_stats_printed is None or (now - last_stats_printed).total_seconds() >= 3600:
                    log_stats(cur)
                    last_stats_printed = now
