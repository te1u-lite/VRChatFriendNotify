from __future__ import annotations
import time,threading
from colorama import init as colorma_init,just_fix_windows_console
from .settings import SETTINGS
from .logging_config import configure_logging
from .http_client import VRChatHTTP
from .vrchat_api import VRChatAPI
from .ws_client import WSRunner
from .snapshot import print_initial_snapshot
from .notify import notify

def main() -> None:

    try:
        just_fix_windows_console()
    except Exception:
        pass
    colorma_init(autoreset=True,convert=True)

    SETTINGS.validate()
    configure_logging(SETTINGS.debug)

    http = VRChatHTTP()
    api = VRChatAPI(http)

    init_token,display_name = http.ensure_login()
    print("Logged in as:",display_name)

    target_ids = api.fetch_all_friend_ids()
    runner = WSRunner(http,api)
    runner.target_ids =target_ids

    print("Monitoring friends:",len(target_ids))
    print_initial_snapshot(api,target_ids)

    wst = threading.Thread(target=runner.run_forever_with_reconnect,
                            args=(init_token,),daemon=True)
    wst.start()

    notify("VRChat","フレンド監視を開始しました")
    print("Watching... Press Ctrl+C to exit.")

    try:
        while wst.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        print("Exiting...")

if __name__ =="__main__":
    main()
