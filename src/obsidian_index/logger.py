import logging

from pythonjsonlogger import jsonlogger

logger = logging.getLogger()
logger.setLevel(logging.INFO)

logHandler = logging.StreamHandler()

formatter = jsonlogger.JsonFormatter(timestamp=True)
logHandler.setFormatter(formatter)

for handler in logger.handlers:
    logger.removeHandler(handler)
logger.addHandler(logHandler)
