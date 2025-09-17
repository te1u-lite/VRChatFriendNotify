from __future__ import annotations
import os
from pathlib import Path
import platform

APP_NAME = "vrcfriendwatch"

def app_dir()->Path:
    if platform.system() == "Windows":
        base = Path(os.getenv("APPDATA",Path.home()/"AppData/Roaming"))
    elif platform.system() =="Darwin":
        base = Path.home()/"Library/Application Support"
    else:
        base = Path(os.getenv("XDG_DATA_HOME",Path.home()/".local/share"))
    p=base / APP_NAME
    p.mkdir(parents=True,exist_ok=True)
    return p

COOKIES_PATH = app_dir()/".vrchat_cookies.pkl"
LOG_PATH = app_dir()/"app.log"

