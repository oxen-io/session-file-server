from . import config
import coloredlogs

coloredlogs.install(level=config.log_level, milliseconds=True, isatty=True)
