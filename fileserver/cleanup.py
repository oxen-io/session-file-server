from flask import current_app
from .web import app
from . import db
from . import config
from .timer import timer
from .stats import log_stats

from datetime import datetime
import requests

last_stats_printed = None

def insert_release_notes_and_assets(cur, project, release):
    if release:
        version = release['tag_name']
        assets = release.get('assets')

        cur.execute(
            """
            INSERT INTO release_notes (project, version, name, notes) VALUES (%s, %s, %s, %s)
            """,
            (project, version, release.get('name'), release.get('body')),
        )

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
                    SELECT project, version, prerelease_version FROM release_versions
                    WHERE updated < NOW() + '30 minutes ago' LIMIT 1
                    """
                )
                row = cur.fetchone()
                if row:
                    project, old_v, old_prerelease_v = row
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

                    prerelease = next((r for r in recent if r.get('prerelease')), False)
                    prerelease_v = None

                    if prerelease:
                        prerelease_v = prerelease["tag_name"]

                    cur.execute(
                        """
                        UPDATE release_versions SET updated = NOW(), version = %s, prerelease_version = %s
                        WHERE project = %s""",
                        (v, prerelease_v, project),
                    )

                    # Update release notes and assets
                    cur.execute(
                        """
                        DELETE FROM release_notes
                        WHERE project = %s""",
                        (project,),
                    )
                    cur.execute(
                        """
                        DELETE FROM release_assets
                        WHERE project = %s""",
                        (project,),
                    )

                    insert_release_notes_and_assets(cur, project, latest)
                    insert_release_notes_and_assets(cur, project, prerelease)

                now = datetime.now()
                global last_stats_printed
                if last_stats_printed is None or (now - last_stats_printed).total_seconds() >= 3600:
                    log_stats(cur)
                    last_stats_printed = now
