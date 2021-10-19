import logging

class timer:
    """Wrapper around a uwsgi timer that fails gracefully when we aren't under uwsgi.  When such a
    failure occurs the timer does not run."""
    def __init__(self, secs):
        try:
            import uwsgi
            self.secs = secs
        except ModuleNotFoundError:
            import sys
            logging.error("""
            WARNING:

            uwsgidecorators not installed or not running under uwsgi.
            File cleanup and session version updating will not be enabled!
            """)
            self.secs = None

    def __call__(self, f):
        if self.secs is None:
            return
        import uwsgi
        signum = None
        for n in range(256):
            if not uwsgi.signal_registered(n):
                signum = n
                break
        if signum is None:
            raise RuntimeError("Could not find a free uwsgi signal slot")
        uwsgi.register_signal(signum, '', f)
        uwsgi.add_timer(signum, self.secs)
        return f

