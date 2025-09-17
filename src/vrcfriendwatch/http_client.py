from __future__ import annotations
import os
import time
import re
import pickle
import logging
import requests
import pyotp
import sys
import random

from .settings import SETTINGS
from .paths import COOKIES_PATH

log = logging.getLogger(__name__)

TOTP_VERIFY_URL  = "https://api.vrchat.cloud/api/1/auth/twofactorauth/totp/verify"
EMAIL_VERIFY_URL = "https://api.vrchat.cloud/api/1/auth/twofactorauth/emailotp/verify"


class VRChatHTTP:
    def __init__(self) -> None:
        self.s = requests.Session()
        self.s.headers["User-Agent"] = SETTINGS.user_agent
        self._load_cookies()

    # --- cookies ---
    def _load_cookies(self) -> None:
        if COOKIES_PATH.exists():
            try:
                self.s.cookies.update(pickle.loads(COOKIES_PATH.read_bytes()))
            except Exception:
                log.warning("Cookie load failed", exc_info=SETTINGS.debug)

    def _save_cookies(self) -> None:
        try:
            COOKIES_PATH.write_bytes(pickle.dumps(self.s.cookies))
        except Exception:
            # exv_info → exc_info に修正
            log.warning("Cookie save failed", exc_info=SETTINGS.debug)

    # --- auth/user ---
    def auth_user(self) -> dict:
        r = self.s.get("https://api.vrchat.cloud/api/1/auth/user")
        if r.status_code == 401:
            r = self.s.get(
                "https://api.vrchat.cloud/api/1/auth/user",
                auth=(SETTINGS.username, SETTINGS.password),
            )
        r.raise_for_status()
        return r.json()

    # --- cookie extraction  ---
    def extract_auth_cookie(self) -> str | None:
        """requests.Session から auth クッキー値を取り出す"""
        auth_token = self.s.cookies.get("auth")
        if not auth_token:
            for c in self.s.cookies:
                if c.name.lower().startswith("auth"):
                    auth_token = c.value
                    break
        return auth_token

    # 互換のためのエイリアス（既存コードが _extract_auth_cookie を呼んでもOK）
    _extract_auth_cookie = extract_auth_cookie

    def _needs_2fa(self,user_json:dict | None)->bool:
        if not isinstance(user_json,dict):
            return True

        if "displayName" not in user_json:
            return True
        if user_json.get("requiresTwoFactorAuth")or user_json.get("requiresTwoFactorAuthMessage"):
            return True

        return False

    def _clean_totp_secret(self,raw: str | None)->str:
        """空白/改行を除去し大文字化。Base32以外の文字が混ざっていたらログ警告。"""
        secret = "".join((raw or "").split()).upper()
        if not secret:
            return ""
        if re.search(r"[^A-Z2-7=]",secret):
            log.warning("TOTP secret に Base32 以外の文字が含まれている可能性があります。")
        return secret

    def _post_json_with_rate_limit(self, url: str, payload: dict,
                                    max_tries: int = 3, base_sleep: float = 2.0) -> requests.Response:
        """
        429 Too Many Requests のとき Retry-After を待ってから再試行する共通POSTヘルパー。
        429以外のステータスはそのまま返す（呼び出し側で raise_for_status() する）。
        """
        last = None
        for i in range(max_tries):
            resp = self.s.post(url, json=payload)
            last = resp
            if resp.status_code != 429:
                return resp
            # 429: ヘッダーの Retry-After（秒）を優先し、なければ指数バックオフ
            ra = resp.headers.get("Retry-After")
            try:
                wait = float(ra) if ra is not None else base_sleep * (2 ** i)
            except Exception:
                wait = base_sleep * (2 ** i)
            wait += random.uniform(0, 0.5)  # ジッター
            log.warning("429 on %s. Backing off for %.1fs (try %d/%d)", url, wait, i + 1, max_tries)
            time.sleep(wait)
        # 規定回数リトライ後の最後のレスポンスを返す（呼び出し側で raise_for_status してください）
        return last

    def _verify_email_otp_with_prompt(self, tries: int = 3) -> None:
        """コンソールでメールOTPを入力させて検証。429は待って再試行。成功で return、失敗で例外。"""
        if not sys.stdin or not sys.stdin.isatty():
            raise RuntimeError("コンソール入力が利用できません（メールOTP優先）。TOTP を設定するか、コンソールで実行してください。")
        for i in range(tries):
            code = input("Enter Email OTP code: ").strip()
            resp = self._post_json_with_rate_limit(EMAIL_VERIFY_URL, {"code": code}, max_tries=3, base_sleep=3.0)
            try:
                resp.raise_for_status()
            except requests.HTTPError:
                # 400などはそのまま失敗扱い（429はヘルパー側で待ち済み）
                log.error("Email OTP verify failed (try %d/%d): %s", i+1, tries, resp.text)
                if i < tries - 1:
                    continue
                raise
            if (resp.json() or {}).get("verified", True):
                log.info("2FA: verified via Email OTP")
                return
            log.error("Email OTP not verified (try %d/%d).", i+1, tries)
            if i < tries - 1:
                time.sleep(1.0)
        raise RuntimeError("Email OTP verification failed for all attempts.")


    def _verify_totp_with_retry(self,secret: str)->None:
        """
        現在時刻のコード → 前の30秒 → 次の30秒 の順に最大3回トライ。
        いずれかが200&verified=Trueなら成功。失敗はHTTPErrorを投げる。
        """
        url = "https://api.vrchat.cloud/api/1/auth/twofactorauth/totp/verify"
        #今/前/次の3スロットを試す
        for offset in (0,-30,30):
            code = pyotp.TOTP(secret).at(int(time.time())+offset)
            resp = self.s.post(url,json={"code":code})
            try:
                resp.raise_for_status()
            except requests.HTTPError:
                #400のときは次スロットを試す (ログはDEBUGに)
                log.debug("TOTP verify failed (%s): %s",resp.status_code,resp.text)
                if resp.status_code ==400:
                    continue
                raise
            #200 OK
            j = (resp.json() or {})
            if j.get("verified"):
                log.info("2FA: verified via TOTP (offset=%ss)",offset)
                return
            #200だがverified Falseの場合も念のため次へ
            log.debug("TOTP verify response but not verified: %s",j)
        #3スロットともNG
        raise requests.HTTPError("TOTP verification failed for all time windows (now/-30/+30)")

    # --- ensure login ---
    def ensure_login(self) -> tuple[str, str]:
        try:
            data = self.auth_user()
        except Exception:
            r = self.s.get(
                "https://api.vrchat.cloud/api/1/auth/user",
                auth=(SETTINGS.username, SETTINGS.password),
            )
            r.raise_for_status()
            data = r.json()

        auth = self.extract_auth_cookie()
        if not auth:
            raise RuntimeError("auth cookie not found; check credentials and USER_AGENT")

        if self._needs_2fa(data):
            secret = self._clean_totp_secret(SETTINGS.totp_secret)
            prefer_email = (SETTINGS.twofa_preferred =="EMAIL")or (os.getenv("VRCHAT_ALLOW_STDIN_OTP")=="1")

            if prefer_email and os.getenv("VRCHAT_ALLOW_STDIN_OTP") == "1":
            # Email 先行
                try:
                    # 直前にTOTPを叩いていないが、他プロセス等の影響で429の可能性があるため軽く待機
                    time.sleep(0.5)
                    self._verify_email_otp_with_prompt()
                    data = self.auth_user()
                except Exception as e_email:
                    log.warning("Email OTP failed (%s). Trying TOTP as fallback.", e_email)
                    if secret:
                        try:
                            time.sleep(1.0)  # 切替時のレート緩和
                            self._verify_totp_with_retry(secret)
                            data = self.auth_user()
                        except Exception as e_totp:
                            raise RuntimeError(f"Both Email OTP and TOTP failed: {e_email} / {e_totp}")
                    else:
                        raise
            else:
                # TOTP 先行（AUTO か TOTP 指定時）
                if secret:
                    try:
                        self._verify_totp_with_retry(secret)
                        data = self.auth_user()
                    except Exception as e_totp:
                        # 許可されていれば Email にフォールバック
                        if os.getenv("VRCHAT_ALLOW_STDIN_OTP") == "1":
                            log.warning("TOTP failed (%s). Falling back to Email OTP.", e_totp)
                            time.sleep(1.0)
                            self._verify_email_otp_with_prompt()
                            data = self.auth_user()
                        else:
                            raise
                elif os.getenv("VRCHAT_ALLOW_STDIN_OTP") == "1":
                    self._verify_email_otp_with_prompt()
                    data = self.auth_user()
                else:
                    raise RuntimeError(
                        "2FA が必要です。メールOTPを使うには VRCHAT_ALLOW_STDIN_OTP=1 を、"
                        "TOTP を使うには VRCHAT_TOTP_SECRET を設定してください。"
                    )

            # 2FA 後の auth を念のため取り直す
            new_auth = self.extract_auth_cookie()
            if new_auth:
                auth = new_auth

        self._save_cookies()
        return auth, (data.get("displayName") if isinstance(data, dict) else "(unknown)")