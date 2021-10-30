# Configuration options
#

import logging


# This sucks: current versions of Session are entirely inflexible as to the data received: they
# *must* get back an integer value for the id, and shove the integer into a double which means we
# can only (perfectly) represent integers from [0, 2^53].
BACKWARDS_COMPAT_IDS = True


# Use this bit suffix in generated backwards compatible integer IDs.  This is intended to avoid
# synchronization conflicts when setting up multi-master database synchronization.  The bits added
# here (which must be an array of 0 or 1s) will be hard-coded into the most significant bits of the
# value, then the remaining 53-bit determined randomly.  E.g. 1 reserved bit is enough for 2
# servers, 2 is enough for 4, etc.  Each server in a cluster should have a different bit pattern
# with exactly the same number of fixed bits.  Should be empty for a single server file server.
BACKWARDS_COMPAT_IDS_FIXED_BITS = []

# Maximum file size we will accept, in bytes.  This should generally be the same as Session's value,
# and has to be small enough that it can fit, post-base64 encoding + onion wrapping, into the 10MB
# size limit of storage server messages.
MAX_FILE_SIZE = 6_000_000

# Same as above, but for a base64-encoded string
MAX_FILE_SIZE_B64 = 8_000_000

# File expiry, in a postgresql-compatible duration relative to `now()`.  Be aware if using `days` or
# larger units that postgresql days and months are variable: a day could be 23-25 hours (if it
# crosses a DST change), and a month could be 28-31 days ± 1 hour.  If you need a precise interval,
# use a precise unit.
FILE_EXPIRY = '3 weeks'


# postgresql connect options
pgsql_connect_opts = {
    "dbname": "sessionfiles",
}

# The default log level
log_level = logging.INFO
