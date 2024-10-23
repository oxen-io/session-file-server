from flask import current_app
from .web import app
from . import db
from . import config
from .timer import timer
from .stats import log_stats

import re
from datetime import datetime
import requests

last_stats_printed = None


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
                    SELECT id, name FROM projects
                    WHERE updated < NOW() + '30 minutes ago' LIMIT 1
                    """
                )
                row = cur.fetchone()
                if row:
                    projid, project = row
                    latest = requests.get(
                        f"https://api.github.com/repos/{project}/releases/latest", timeout=5
                    ).json()

                    # If the latest release doesn't have version information then don't bother continuing
                    # this means something is invalid, or we were rate limited
                    if 'tag_name' not in latest:
                        app.logger.warn(
                            f"'tag_name' key not found in latest release for project {project}"
                        )
                        continue

                    recent = requests.get(
                        f"https://api.github.com/repos/{project}/releases?per_page=3", timeout=5
                    ).json()

                    with psql.transaction():
                        for release in recent:
                            v = release["tag_name"]
                            vresult = re.match(r'v?(\d{1,3})\.(\d{1,3})\.(\d{1,3})$', v)
                            if not vresult:
                                app.logger.warn(
                                    f"Unknown {project} tag does not look like a x.y.z version: {v}'"
                                )
                                continue
                            vcode = (
                                1000000 * int(vresult.group(1))
                                + 1000 * int(vresult.group(2))
                                + int(vresult.group(3))
                            )

                            cur.execute(
                                """
                                INSERT INTO releases (project, prerelease, version_code, url, name, notes)
                                VALUES (%s, %s, %s, %s, %s, %s)
                                ON CONFLICT(project, version_code) DO UPDATE SET
                                    prerelease = EXCLUDED.prerelease,
                                    url = EXCLUDED.url,
                                    name = EXCLUDED.name,
                                    notes = EXCLUDED.notes
                                    WHERE releases.prerelease != EXCLUDED.prerelease
                                        OR releases.url != EXCLUDED.url
                                        OR releases.name != EXCLUDED.name
                                        OR releases.notes != EXCLUDED.notes
                                    RETURNING id
                                """,
                                (
                                    projid,
                                    bool(release.get("prerelease")),
                                    vcode,
                                    release.get("html_url"),
                                    release.get("name"),
                                    release.get("body"),
                                ),
                            )
                            row = cur.fetchone()
                            if row:
                                relid = row[0]
                                # We either inserted or updated the row, so clear any assets and
                                # readd them (in case the upload assets changed)
                                cur.execute(
                                    "DELETE FROM release_assets WHERE release = %s", (relid,)
                                )
                                for asset in release.get('assets', []):
                                    cur.execute(
                                        "INSERT INTO release_assets (release, name, url) VALUES (%s, %s, %s)",
                                        (relid, asset['name'], asset['url']),
                                    )

                        cur.execute("UPDATE projects SET updated = NOW() WHERE id = %s", (projid,))

                now = datetime.now()
                global last_stats_printed
                if last_stats_printed is None or (now - last_stats_printed).total_seconds() >= 3600:
                    log_stats(cur)
                    last_stats_printed = now
