import json
import os
import re
import threading
import time
import random
from dotenv import load_dotenv

from websocket import WebSocketApp
from win11toast import toast
import requests

from contextlib import redirect_stdout
from io import StringIO

import pickle
import pyotp

import traceback

from colorama import init as colorama_init, Fore,Back, Style
colorama_init(autoreset=True)

load_dotenv()

USERNAME = os.getenv("VRCHAT_USERNAME")
PASSWORD = os.getenv("VRCHAT_PASSWORD")
USER_AGENT = os.getenv("VRCHAT_USER_AGENT", "VRCFriendWatch/1.0 your-contact@example.com")

TOTP_SECRET = os.getenv("VRCHAT_TOTP_SECRET")
COOKIE_FILE = ".vrchat_cookies.pkl"

#キャッシュ
_DISPLAY_NAME_CACHE = {}
_WORLD_NAME_CACHE = {}

#グローバルセッションを1個だけ作って使いまわす
_SESSION = requests.Session()
_SESSION.headers["User-Agent"] = USER_AGENT

def load_cookies():
    if os.path.exists(COOKIE_FILE):
        try:
            with open(COOKIE_FILE,"rb") as f:
                _SESSION.cookies.update(pickle.load(f))
        except Exception:
            pass

def save_cookies():
    try:
        with open(COOKIE_FILE,"wb")as f:
            pickle.dump(_SESSION.cookies,f)
    except Exception:
        pass

print(USERNAME)

def notify(title: str, msg: str, duration=5):
    buf = StringIO()
    with redirect_stdout(buf):
        if duration and duration >= 25:
            toast(title, msg, duration="long")
        else:
            toast(title, msg)

def fetch_all_friend_ids() -> set[str]:
    ids: set[str] = set()
    for offline in (True,False):
        for f in _list_friends(offline):
            uid = f.get("id")or f.get("userId")
            if uid:
                ids.add(uid)
    return ids

def _fetch_display_name(user_id: str)->str:
    """ユーザIDからdisplayNameを取得してキャッシュ"""
    if not user_id:
        return ""
    if user_id in _DISPLAY_NAME_CACHE:
        return _DISPLAY_NAME_CACHE[user_id]
    try:
        r = _SESSION.get(f"https://api.vrchat.cloud/api/1/users/{user_id}")
        if r.ok:
            dn = (r.json() or {}).get("displayName","")
            if dn:
                _DISPLAY_NAME_CACHE[user_id]=dn
                return dn
    except Exception:
        pass
    return ""

def _world_Name_from_id(world_id: str)->str:
    """world_id (wrld_...) → ワールド名を取得してキャッシュ"""
    if not world_id:
        return ""
    if world_id in _WORLD_NAME_CACHE:
        return _WORLD_NAME_CACHE[world_id]
    try:
        r = _SESSION.get(f"https://api.vrchat.cloud/api/1/worlds/{world_id}")
        if r.ok:
            name = (r.json() or {}).get("name","")
            if name:
                _WORLD_NAME_CACHE[world_id]=name
                return name
    except Exception:
        pass
    return world_id #取得失敗時はIDをそのまま返す

_LOC_RE = re.compile(r"^(wrld_[0-9a-fA-F-]+)(?::(.+))?$")

def _parse_location_to_worldName(location: str)->str:
    """
    location文字列からワールド名へ
    - 'wrld_xxx:instance...' → APIで名前解決
    - 'private', 'offline', 'traveling' など → そのまま
    """
    if not location :
        return "(unknown)"
    m = _LOC_RE.match(location)
    if m:
        world_id= m.group(1)
        world_name = _world_Name_from_id(world_id)
        return world_name
    return location

def _status_color(status: str)->str:
    """
    ステータス文字列に応じた色を返す
    active/online=緑,busy=赤,join me=シアン,それ以外=デフォルト
    """
    if not status:
        return ""
    s = status.lower()
    if s in ("active","online"):
        return Fore.GREEN
    if s in ("busy"):
        return Fore.RED
    if s in ("join me","joinme"):
        return Fore.CYAN
    if s in ("ask me","askme","away"):
        return Fore.YELLOW
    return Fore.WHITE

def get_auth_cookie_and_name():
    """
    共有 _SESSIONを使ってログインし、authクッキーとdisplayNameを返す。
    可能ならTOTPを自動検証。失敗時のみEmail OTPにフォールバック
    """
    s=_SESSION

    #まずは既存クッキーで試す
    r = s.get("https://api.vrchat.cloud/api/1/auth/user")
    if r.status_code == 401:
        #401の時だけBasic認証でログイン試行
        r = s.get("https://api.vrchat.cloud/api/1/auth/user",auth=(USERNAME,PASSWORD))
    r.raise_for_status()

    #authクッキー取得
    auth_token = s.cookies.get("auth")
    if not auth_token:
        for c in s.cookies:
            if c.name.lower().startswith("auth"):
                auth_token = c.value
                break
    if not auth_token:
        raise RuntimeError("auth cookie not found; check credentials and USER_AGENT")

    #2FA判定
    data={}
    try:
        data = r.json()
    except Exception:
        pass

    if not isinstance(data,dict)or "displayName"not in data:
        # 1)TOTP自動
        if TOTP_SECRET:
            code = pyotp.TOTP(TOTP_SECRET).now()
            resp = s.post(
                "https://api.vrchat.cloud/api/1/auth/twofactorauth/totp/verify",
                json = {"code":code},
            )
            if resp.ok and resp.json().get("verified"):
                data = s.get("https://api.vrchat.cloud/api/1/auth/user").json()
                save_cookies()
                return auth_token,data["displayName"]
        # 2)フォールバック:Email OTP
        code = input("Enter Email OTP code: ").strip()
        resp = s.post(
            "https://api.vrchat.cloud/api/1/auth/twofactorauth/emailotp/verify",
            json={"code":code},
        )
        resp.raise_for_status()
        data = s.get("https://api.vrchat.cloud/api/1/auth/user").json()

    save_cookies()
    return auth_token,data["displayName"]


def make_ws(auth_token):
    url = f"wss://pipeline.vrchat.cloud/?authToken={auth_token}"
    headers = [f"User-Agent: {USER_AGENT}", "Origin: https://vrchat.com"]
    print(f"[WS] connecting to: {url}")  # ★ 追加
    print(f"[WS] headers: {headers}")     # ★ 追加
    return WebSocketApp(
        url,
        header=headers,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )


def run_forever_with_reconnect(initial_auth_token=None):
    backoff = 1
    auth_token = initial_auth_token
    last_auth_ok =time.time() if initial_auth_token else 0

    while True:
        #まずは現在のトークンでWSを張ってみる
        if auth_token is None:
            try:
                auth_token,display_name = get_auth_cookie_and_name()
                print("Logged in as:",display_name)


                last_auth_ok = time.time()
                backoff = 1
            except Exception as e:
                print("Re-auth failed:",e)
                time.sleep(5)
                continue
        ws=make_ws(auth_token)
        try:
            ws.run_forever(ping_interval=55,ping_timeout=20,skip_utf8_validation=True)
        except Exception as e:
            print("WS run_forever error:",e)

        #ここに来たら切断されたので再接続するが、即再認証はしない
        #いったん待ってから同じauth_tokenで再接続。サーバに拒否されたら次ループでauth_tokenを捨てる
        sleep = min(backoff,30)+random.uniform(0,1.0)
        print(f"Reconnecting in {sleep:.1f}s...")
        time.sleep(sleep)
        backoff = min(backoff*2,30)

        #サニティチェック : HTTP側でトークンがまだ有効かを"クッキーのみ"で確認
        try:
            r = _SESSION.get("https://api.vrchat.cloud/api/1/auth/user")
            if r.status_code==401:
                #無効化されているので次ループで再認証させる
                auth_token = None
            else:
                last_auth_ok = time.time()
        except Exception:
            #ネットワーク例外はスキップ(再接続ループに任せる)
            pass

def _name_or_id(user_id: str)->str:
    dn = _fetch_display_name(user_id)
    return dn or user_id or "(unknown)"

def on_message(ws, raw):
    # content が二重 JSON のことがある
    try:
        msg = json.loads(raw)
    except Exception:
        print("Non-JSON", raw)
        return

    typ = msg.get("type")
    content = msg.get("content")

    if isinstance(content, str):
        try:
            content = json.loads(content)
        except Exception:
            pass

    if typ in ("friend-online", "friend-offline", "friend-location", "friend-update"):
        uid = None
        if isinstance(content,dict):
            uid = (content or {}).get("userId")\
                or (content.get("user")or {}).get("id")\
                or content.get("id")

        if not uid:
            print (Fore.MAGENTA + f"[DROP] event type={typ} has no user id. content keys={list((content or {}).keys())}"+Style.RESET_ALL)
            return

        if VRCHAT_TARGET_USER_IDS and uid not in VRCHAT_TARGET_USER_IDS:
            print(Fore.MAGENTA + f"[DROP] uid={uid} not in target set (|targets|={len(VRCHAT_TARGET_USER_IDS)})"+Style.RESET_ALL)
            return

        name_show = _name_or_id(uid)

        if typ == "friend-online":
            loc = (content or {}).get("location","")
            notify("VRChat",f"{name_show} がオンラインになりました")
            #緑色でログ
            print(Fore.GREEN+f"[ONLINE] {name_show} ({uid}) location={loc}"+Style.RESET_ALL)

        elif typ == "friend-offline":
            notify("VRChat",f"{name_show} がオフラインになりました")
            #赤色でログ
            print(Fore.RED+f"[OFFLINE] {name_show} ({uid})"+Style.RESET_ALL)

        elif typ == "friend-location":
            loc_raw = (content or {}).get("location","")
            world_or_state = _parse_location_to_worldName(loc_raw)
            notify("VRChat",f"{name_show} が移動: {world_or_state}")
            #クリーム色でログ
            print(Back.LIGHTYELLOW_EX+Fore.BLACK +f"[MOVE] {name_show} ({uid}) -> {world_or_state}"+Style.RESET_ALL)

        elif typ == "friend-update":
            #ステータス変更など
            new_status = (content or {}).get("status")
            status_desc = (content or {}).get("statusDescription","")
            status_fg = _status_color(new_status)
            notify("VRChat",f"{name_show}のステータス更新: {new_status or 'unknown'}")
            #クリーム色+ステータス色
            prefix = Back.LIGHTYELLOW_EX + Fore.BLACK + "[UPDATE] "+Style.RESET_ALL
            status_part = (Back.LIGHTYELLOW_EX + status_fg+f" status={new_status or '(unknown)'}"+Style.RESET_ALL)
            desc_part=f" desc={status_desc}"if status_desc else ""
            print(prefix+f"{name_show} ({uid}) "+status_part+desc_part)

def _uid_from_obj(o:dict)->str | None:
    if not isinstance(o,dict):
        return None
    return(
        o.get("id")
        or o.get("userId")
        or (o.get("user")or {}).get("id")
        or o.get("userID")
    )

def _list_friends(offline: bool,batch_size: int = 100)->list[dict]:
        """VRChat APIの仕様に合わせ、offline=Trueはオフラインのみ、Falseはオンライン+Webアクティブのみを返す。"""
        out = []
        offset = 0
        batch_size = min(int(batch_size),100)
        while True:
            try:
                r = _SESSION.get(
                    "https://api.vrchat.cloud/api/1/auth/user/friends",
                    params = {"offset":offset, "n": batch_size,"offline": "true" if offline else "false"},
                )
                if not r.ok:
                    print(f"Failed to fetch friends (offline={offline}): {r.status_code} {r.reason}")
                    try:
                        print("Response:",r.text[:500])
                    except Exception:
                        pass
                    break
                chunk = r.json()or []
                if not isinstance(chunk,list)or not chunk:
                    break
                out.extend(chunk)
                if len(chunk)<batch_size:
                    break
                offset += batch_size
            except Exception as e:
                print(f"Failed to fetch friends (offline = {offline}):",e)
                break
        return out


def on_error(ws, err):
    print("WS error:", err)
    traceback.print_exc()  # ★ 追加: スタックトレースで原因特定


def on_close(ws, code, msg):
    print("WS closed:", code, msg)
    notify("VRChat", "WebSocketが切断されました (自動再接続中)")


def on_open(ws):
    print("WS connected")


def print_initial_snapshot(target_ids: set[str]):
    try:
        all_friends = _list_friends(offline=True)+_list_friends(offline=False)

        # userIdで重複排除（APIの戻りが 'id' のことが多いが念のため両対応）
        by_id: dict[str, dict] = {}
        for f in all_friends:
            uid = _uid_from_obj(f)
            if uid:
                by_id[uid] = f
        all_friends = list(by_id.values())

        show_ids = target_ids or {_uid_from_obj(f)for f in all_friends if _uid_from_obj(f)}

        print("---- Initial Snapshot ----")

        dropped = 0
        for f in all_friends:
            uid = _uid_from_obj(f)
            if not uid:
                dropped+=1
                continue
            if uid not in show_ids:
                dropped+=1
                continue

            name = f.get("displayName") or _name_or_id(uid)
            status = f.get("status")or "unknown"
            location = f.get("location") or ""
            world = _parse_location_to_worldName(location)
            color = _status_color(status)
            print(color + f"{name} ({uid}) status={status} location={world}"+Style.RESET_ALL)

        if dropped:
            print(Fore.MAGENTA + f"[SNAPSHOT] dropped entries: {dropped} (id missing or not in target set)" + Style.RESET_ALL)
        print(Fore.CYAN + f"[SNAPSHOT] |all_friends|={len(all_friends)} |targets|={len(show_ids)}"+Style.RESET_ALL)

    except Exception as e:
        print("Initial snapshot error:",e)

if __name__ == "__main__":
    if not (USERNAME and PASSWORD):
        raise SystemExit(
            "環境変数 VRCHAT_USERNAME/VRCHAT_PASSWORD を設定してください(.env推奨)"
        )

    #クッキー復元
    load_cookies()

    #まず既存クッキーで/auth/userを試す (basicなし)
    init_token =None
    try:
        r = _SESSION.get("https://api.vrchat.cloud/api/1/auth/user")
        if r.status_code ==401:
            #401のときだけログイン (この時だけBasicを付ける)
            init_token,display_name=get_auth_cookie_and_name()
        else:
            data = r.json()
            #すでにログイン状態
            #クッキーからauthを拾う
            init_token = _SESSION.cookies.get("auth")
            if not init_token:
                for c in _SESSION.cookies:
                    if c.name.lower().startswith("auth"):
                        init_token = c.value
                        break
            display_name = data.get("displayName","(unknown)")
    except Exception:
        #例外時は正攻法でログイン
        init_token,display_name = get_auth_cookie_and_name()

    print ("Logged in as:",display_name)

    VRCHAT_TARGET_USER_IDS = fetch_all_friend_ids()

    print("Monitoring friends:",len(VRCHAT_TARGET_USER_IDS))

    for _uid in list(VRCHAT_TARGET_USER_IDS):
        _ = _fetch_display_name(_uid)

    print_initial_snapshot(VRCHAT_TARGET_USER_IDS)

    wst = threading.Thread(target =run_forever_with_reconnect,args=(init_token,),daemon=True)
    wst.start()

    notify("VRChat","フレンド監視を開始しました")
    print("Watching... Press Ctrl+C to exit.")

    try:
        while wst.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        print("Exiting...")
