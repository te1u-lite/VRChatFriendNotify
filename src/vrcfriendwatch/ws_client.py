# ws_client.py（該当部分だけ差し替え）

from __future__ import annotations
import time, random, logging, traceback, json
from websocket import WebSocketApp
from colorama import Fore, Back, Style
from .settings import SETTINGS
from .notify import notify
from .vrchat_api import VRChatAPI
from .http_client import VRChatHTTP

log = logging.getLogger(__name__)

def status_color(s: str | None) -> str:
    if not s: return ""
    s = s.lower()
    if s in ("active", "online"): return Fore.GREEN
    if s in ("busy",):            return Fore.RED
    if s in ("join me", "joinme"):return Fore.CYAN
    if s in ("ask me", "askme", "away"): return Fore.YELLOW
    return Fore.WHITE

class WSRunner:
    def __init__(self, http: VRChatHTTP, api: VRChatAPI):
        self.http, self.api = http, api
        self.target_ids: set[str] = set()

    def make_ws(self, auth_token: str) -> WebSocketApp:
        url = f"wss://pipeline.vrchat.cloud/?authToken={auth_token}"
        headers = [f"User-Agent: {SETTINGS.user_agent}", "Origin: https://vrchat.com"]
        log.info("[WS] connecting: %s", url)
        return WebSocketApp(
            url, header=headers,
            on_open=self.on_open, on_message=self.on_message,
            on_error=self.on_error, on_close=self.on_close,
        )

    def run_forever_with_reconnect(self, initial_auth: str | None = None) -> None:
        backoff, auth = 1, initial_auth
        while True:
            if not auth:
                auth, name = self.http.ensure_login()
                log.info("Logged in as: %s", name)
                backoff = 1
            ws = self.make_ws(auth)
            try:
                ws.run_forever(ping_interval=55, ping_timeout=20, skip_utf8_validation=True)
            except Exception as e:
                log.error("WS run_forever error: %s", e)

            sleep = min(backoff, 30) + random.uniform(0, 1.0)
            log.info("Reconnecting in %.1fs...", sleep)
            time.sleep(sleep)
            backoff = min(backoff * 2, 30)

            try:
                r = self.http.s.get("https://api.vrchat.cloud/api/1/auth/user")
                if r.status_code == 401:
                    auth = None
            except Exception:
                pass

    # --- Handlers ---
    def on_open(self, ws): log.info("WS connected")

    def on_error(self, ws, err):
        log.error("WS error: %s", err)
        if SETTINGS.debug: traceback.print_exc()

    def on_close(self, ws, code, msg):
        log.warning("WS closed: %s %s", code, msg)
        notify("VRChat", "WebSocketが切断されました (自動再接続中)")

    def on_message(self, ws, raw):
        try:
            msg = json.loads(raw)
        except Exception:
            log.debug("Non-JSON: %s", raw)
            return

        typ = msg.get("type")
        content = msg.get("content")
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except Exception:
                pass

        # ✨ ここを 'typ' に
        if typ not in ("friend-online", "friend-offline", "friend-location", "friend-update"):
            return

        uid = (
            (content or {}).get("userId")
            or (content.get("user") or {}).get("id")
            or (content or {}).get("id")
        )
        if not uid:
            log.debug("[DROP] type=%s no user id", typ)
            return
        if self.target_ids and uid not in self.target_ids:
            log.debug("[DROP] uid=%s not in target set", uid)
            return

        name = self.api.display_name(uid) or uid

        if typ == "friend-online":
            notify("VRChat", f"{name} がオンラインになりました")  # ← f-string 修正
            print(Fore.GREEN + f"[ONLINE] {name} ({uid})" + Style.RESET_ALL)

        elif typ == "friend-offline":
            notify("VRChat", f"{name} がオフラインになりました")
            print(Fore.RED + f"[OFFLINE] {name} ({uid})" + Style.RESET_ALL)

        elif typ == "friend-location":  # ← ここも typ
            loc_raw = (content or {}).get("location", "")
            world = self.api.parse_location_to_world(loc_raw)
            notify("VRChat", f"{name} が移動: {world}")
            print(Back.LIGHTYELLOW_EX + Fore.BLACK + f"[MOVE] {name} ({uid}) -> {world}" + Style.RESET_ALL)

        elif typ == "friend-update":
            new_status = (content or {}).get("status")
            status_desc = (content or {}).get("statusDescription", "")
            disp_status = new_status or "unknown"  # クォート崩れ防止
            notify("VRChat", f"{name}のステータス更新: {disp_status}")
            color = status_color(new_status)
            prefix = Back.LIGHTYELLOW_EX + Fore.BLACK + "[UPDATE] " + Style.RESET_ALL
            status_part = Back.LIGHTYELLOW_EX + color + f" status={disp_status}" + Style.RESET_ALL
            desc_part = f" desc={status_desc}" if status_desc else ""
            print(prefix + f"{name} ({uid}) " + status_part + desc_part)
