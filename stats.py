
import logging

si_prefixes = ['', 'k', 'M', 'G', 'T', 'P', 'E', 'Z', 'Y']
def pretty_bytes(nbytes):
    i = 0
    while nbytes >= 1000 and i + 1 < len(si_prefix):
        nbytes /= 1000
        i += 1
    return ("{} B" if i == 0 else "{:.1f} {}B").format(nbytes, si_prefixes[i])


def log_stats(cur):
    cur.execute("SELECT COUNT(*), sum(length(data)) FROM files")
    num, size = cur.fetchone()
    if num == 0 and size is None:
        size = 0

    logging.info("Current stats: {} files stored totalling {}".format(
        num, pretty_bytes(size)))
