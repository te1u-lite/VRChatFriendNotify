from __future__ import annotations
import logging, sys
from .paths import LOG_PATH

def configure_logging(debug:bool = False)->None:
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    level = logging.DEBUG if debug else logging.INFO
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_PATH,encoding="utf-8"),
    ]
    logging.basicConfig(level=level,format=fmt,handlers=handlers)