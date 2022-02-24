try:
    import uwsgi  # noqa: F401
except ModuleNotFoundError:

    class postfork:
        """Simple non-uwsgi stub that just calls the postfork function"""

        def __init__(self, f):
            self.f = f
            self.f()

        def __call__(self):
            self.f()


else:
    import uwsgidecorators

    postfork = uwsgidecorators.postfork
