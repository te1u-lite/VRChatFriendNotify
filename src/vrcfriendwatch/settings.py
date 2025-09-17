from __future__ import annotations
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

class Settings:
    username:str = os.getenv("VRCHAT_USERNAME","")
    password: str = os.getenv("VRCHAT_PASSWORD","")
    user_agent:str = os.getenv("VRCHAT_USER_AGENT","VRCFriendWatch/1.0 your-contact@example.com")
    totp_secret: str | None = os.getenv("VRCHAT_TOTP_SECRET")or None
    debug: bool = os.getenv("DEBUG","0")=="1"
    twofa_preferred: str = os.getenv("VRCHAT_2FA_PREFERRED", "AUTO").upper()

    def validate(self)->None:
        if not (self.username and self.password):
            raise SystemExit("環境変数 VRCHAT_USERNAME/VRCHAT_PASSWORD を設定してください　(.env 推奨)")

SETTINGS = Settings()