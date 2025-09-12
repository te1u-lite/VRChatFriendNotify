import json
import os
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

#AUTH_REFRESH_SECS = 30 * 60  # 30分ごとに auth を取り直す

load_dotenv()

USERNAME = os.getenv("VRCHAT_USERNAME")
PASSWORD = os.getenv("VRCHAT_PASSWORD")
USER_AGENT = os.getenv("VRCHAT_USER_AGENT", "VRCFriendWatch/1.0 your-contact@example.com")
VRCHAT_TARGET_USER_ID = os.getenv("VRCHAT_TARGET_USER_ID")

TOTP_SECRET = os.getenv("VRCHAT_TOTP_SECRET")
COOKIE_FILE = ".vrchat_cookies.pkl"

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
        uid = (content or {}).get("userId")
        if uid == VRCHAT_TARGET_USER_ID:
            if typ == "friend-online":
                loc = (content or {}).get("location", "")
                notify("VRChat", "監視対象がオンラインになりました")
                print(f"[ONLINE] {uid} location={loc}")
            elif typ == "friend-offline":
                notify("VRChat", "監視対象がオフラインになりました")
                print(f"[OFFLINE] {uid}")
            elif typ == "friend-location":
                loc = (content or {}).get("location", "")
                notify("VRChat", f"監視対象が移動: {loc}")
                print(f"[MOVE] {uid} -> {loc}")
            elif typ == "friend-update":
                notify("VRChat", "監視対象のプロフィールが更新されました")
                print(f"[UPDATE] {uid}")


def on_error(ws, err):
    print("WS error:", err)


def on_close(ws, code, msg):
    print("WS closed:", code, msg)
    notify("VRChat", "WebSocketが切断されました (自動再接続中)")


def on_open(ws):
    print("WS connected")


if __name__ == "__main__":
    if not (USERNAME and PASSWORD and VRCHAT_TARGET_USER_ID):
        raise SystemExit(
            "環境変数 VRCHAT_USERNAME/VRCHAT_PASSWORD/VRCHAT_TARGET_USER_ID を設定してください(.env推奨)"
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

    wst = threading.Thread(target =run_forever_with_reconnect,args=(init_token,),daemon=True)
    wst.start()

    notify("VRChat","フレンド監視を開始しました")
    print("Watching... Press Ctrl+C to exit.")

    try:
        while wst.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        print("Exiting...")
