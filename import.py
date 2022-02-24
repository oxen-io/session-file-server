#!/usr/bin/env python3

import psycopg
import sys
import os
import os.path
from datetime import datetime

from fileserver import config

psql = psycopg.connect(**config.pgsql_connect_opts, autocommit=True)

if len(sys.argv) != 2 or sys.argv[1].startswith('-'):
    print("Usage: {} /path/to/session-open-group-server".format(sys.argv[0]), file=sys.stderr)
    sys.exit(1)

filesdir = sys.argv[1] + '/files/main_files'

if not os.path.isdir(filesdir):
    print("Error: {} does not exist or is not a directory".format(filesdir), file=sys.stderr)
    sys.exit(2)

cur = psql.cursor()

count = 0
committed_size = 0
skipped = 0
skipped_size = 0
started = datetime.now()
window = [(0, started)]
total_files = sum(1 for _ in os.scandir(filesdir))
for dentry in os.scandir(filesdir):
    if not dentry.name.isdigit() or not dentry.is_file():
        print(
            "\nWARNING: {} doesn't look like an old file server upload, skipping.".format(
                dentry.name
            ),
            file=sys.stderr,
        )
        continue

    stat = dentry.stat()
    size = stat.st_size
    row = cur.execute("SELECT length(data) FROM files WHERE id = %s", (dentry.name,)).fetchone()
    if row:
        if size != row[0]:
            print(
                (
                    "\nWARNING: Skipping duplicate id {} with mismatched size "
                    "(expected {} ≠ actual {})"
                ).format(dentry.name, size, row[0])
            )
        skipped += 1
        skipped_size += size

    else:

        uploaded = datetime.fromtimestamp(stat.st_mtime)
        with open(dentry.path, mode='rb') as f:
            data = f.read()

        cur.execute(
            """
            INSERT INTO files (id, data, uploaded, expiry)
            VALUES (%s, %b, %s, %s + %s)
            """,
            (dentry.name, data, uploaded, uploaded, config.FILE_EXPIRY),
        )
        count += 1
        committed_size += size

    now = datetime.now()
    if (now - window[-1][1]).total_seconds() > 0.5:
        if len(window) >= 10:
            window.pop(0)
        mb = committed_size / 1_000_000
        window.append((mb, now))
        speed = (
            (window[-1][0] - window[0][0]) / (window[-1][1] - window[0][1]).total_seconds()
            if len(window) > 1
            else 0
        )
        print(
            (
                "\rImported {:,} (new: {:,}, skipped: {:,}) / {:,} files containing "
                "{:,.1f}MB new ({:,.2f}MB/s), {:,.1f}MB skipped data"
            ).format(
                count + skipped, count, skipped, total_files, mb, speed, skipped_size / 1_000_000
            ),
            end='',
            flush=True,
        )


duration = (datetime.now() - started).total_seconds()
print(
    """

Import finished: imported {:,} files containing {:,d} bytes of data in {:,.2f} seconds ({:,.2f}MB/s)

Skipped {:,} already-existing files containing {:,} bytes

""".format(
        count,
        committed_size,
        duration,
        committed_size / 1_000_000 / duration,
        skipped,
        skipped_size,
    )
)
