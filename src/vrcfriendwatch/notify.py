from __future__ import annotations
from contextlib import redirect_stdout
from io import StringIO
import logging

log = logging.getLogger(__name__)

try:
    from win11toast import toast as win_toast
    _HAS_WIN_TOAST = True
except Exception:
    _HAS_WIN_TOAST =False

def notify(title: str, msg:str , duration:int =5)->None:
    if _HAS_WIN_TOAST:
        buf = StringIO()
        with redirect_stdout(buf):
            if duration and duration>=25:
                win_toast(title,msg,duration="long")
            else:
                win_toast(title,msg)
    else:
        log.info("[NOTIFY] %s - %s",title,msg)