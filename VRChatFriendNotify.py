import json
import os
import threading
import time
from dotenv import load_dotenv

from websocket import WebSocketApp
from win11toast import toast

import requests

load_dotenv()

USERNAME = os.getenv("VRCHAT_USERNAME")
PASSWORD = os.getenv("VRCHAT_PASSWORD")
USER_AGENT = os.getenv("VRCHAT_USER_AGENT","VRCFriendWatch/1.0 your-contact@example.com")
VRCHAT_TARGET_USER_ID = os.getenv("VRCHAT_TARGET_USER_ID")

def notify(title: str,msg: str, duration=5):
    if duration and duration>=25:
        toast(title,msg,duration='long')
    else:
        toast(title,msg)

def get_auth_cookie_and_name():
    """
    requests.Session()でログインしてauthトークンとdisplayNameを返す
    2FA(TOTP) / Email OTPも処理
    """
    
    s= requests.Session()
    s.headers["User-Agent"] = USER_AGENT #VRCのガイドラインで必須
    # 1)ログイン (未ログインなら Set-Cookie: auth=... が付く)
    r = s.get("https://api.vrchat.cloud/api/1/auth/user",auth=(USERNAME,PASSWORD))
    r.raise_for_status()

    # 2) authクッキー取得 (名前は "auth"。念のため前方一致でも探索)
    auth_token = s.cookies.get("auth")
    if not auth_token:
        for c in s.cookies:
            if c.name.lower().startswith("auth"):
                auth_token = c.value
                break
    if not auth_token:
        raise RuntimeError("auth cookie not found; check credentials and USER_AGENT")

    # 3) 2FAが必要なら検証(まずTOTP、ダメならEmailOTP)
    data={}
    try:
        data =r.json()
    except Exception:
        pass

    if not isinstance(data,dict)or "displayName"not in data:
        code = input("Enter 2FA/Email code: ").strip()
        #TOTP
        resp = s.post(
            "https://api.vrchat.cloud/api/1/auth/twofactorauth/totp/verify",
            json={"code":code},
        )
        if not (resp.ok and resp.json().get("verified")):
            #Email OTP
            resp=s.post(
                "https://api.vrchat.cloud/api/1/auth/twofactorauth/emailotp/verify",
                json={"code":code},
            )
            resp.raise_for_status()
        #再取得
        data = s.get("https://api.vrchat.cloud/api/1/auth/user").json()
    
    return auth_token,data["displayName"]
    
def on_message(ws,raw):
    #使用上contentが[二重にJSON化]されていることがある点に注意
    #https://vrchat.community/websocket
    try:
        msg = json.loads(raw)
    except Exception:
        print("Non-JSON",raw)
        return
    
    typ = msg.get("type")
    content = msg.get("content")

    #contentが文字列ならもう一段パース
    if isinstance(content,str):
        try:
            content = json.loads(content)
        except Exception:
            pass

    if typ in ("friend-online","friend-offline","friend-location","friend-update"):
        uid = (content or {}).get("userId")
        if uid==VRCHAT_TARGET_USER_ID:
            if typ == "friend-online":
                #world情報が空のこともある(プライベート等)ので安全に読む
                loc = (content or {}).get("location","")
                notify("VRChat","監視対象がオンラインになりました")
                print(f"[ONLINE] {uid} location={loc}")
            elif typ == "friend-offline":
                notify("VRChat","監視対象がオフラインになりました")
                print(f"[OFFLINE] {uid}")
            elif typ == "friend-location":
                loc = (content or {}).get("location", "")
                notify("VRChat",f"監視対象が移動: {loc}")
                print(f"[MOVE] {uid} -> {loc}")
            elif typ == "friend-update":
                #ステータス文などが変わったとき
                notify("VRChat", "監視対象のプロフィールが更新されました")
                print(f"[UPDATE] {uid}")

def on_error(ws,err):
    print("WS error:",err)

def on_close(ws,code,msg):
    print("WS closed:",code,msg)
    notify("VRChat","WebSocketが切断されました (自動接続を検討してください)")

def on_open(ws):
    print("WS connected")

if __name__ == "__main__":
    if not(USERNAME and PASSWORD and VRCHAT_TARGET_USER_ID):
        raise SystemExit("環境変数 VRCHAT_USERNAME/VRCHAT_PASSWORD/TARGET_USER_IDを設定してください(.env推奨)")
    
    auth_token,display_name = get_auth_cookie_and_name()
    print("Logged in as:",display_name)

    #WebSocket接続(authCookieをqueryに付与)
    #公式ドキュメントの通り pipelineに接続。User-Agent　要求あり。 
    url = f"wss://pipeline.vrchat.cloud/?authToken={auth_token}"

    headers = [
        f"User-Agent: {USER_AGENT}",
        "Origin: https://vrchat.com"
    ]

    ws = WebSocketApp(
        url,
        header=headers,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )

    #メインスレッドをブロックしないように常駐
    wst = threading.Thread(target=ws.run_forever,kwargs={"ping_interval":30,"ping_timeout":10},daemon =True)
    wst.start()

    notify("VRChat","フレンド監視を開始しました")
    print("Watching... Press Ctrl+C to exit.")

    try:
        while wst.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        ws.close()



