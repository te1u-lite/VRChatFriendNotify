from __future__ import annotations
import os
from dataclasses import dataclass
from dotenv import load_dotenv
from pathlib import Path
import sys
from shutil import copyfile

load_dotenv()
class Settings:
    username:str = os.getenv("VRCHAT_USERNAME","")
    password: str = os.getenv("VRCHAT_PASSWORD","")
    user_agent:str = os.getenv("VRCHAT_USER_AGENT","VRCFriendWatch/1.0 your-contact@example.com")
    totp_secret: str | None = os.getenv("VRCHAT_TOTP_SECRET")or None
    debug: bool = os.getenv("DEBUG","0")=="1"
    twofa_preferred: str = os.getenv("VRCHAT_2FA_PREFERRED", "AUTO").upper()

    rate_limit_per_minute: int =60
    rate_limit_per_minute :int =10

    def validate(self)->None:
        if not (self.username and self.password):
            raise SystemExit("環境変数 VRCHAT_USERNAME/VRCHAT_PASSWORD を設定してください　(.env 推奨)")

SETTINGS = Settings()

def load_env():
    # PyInstaller --onefileでも.exeのあるフォルダを指す
    if getattr(sys,"frozen",False):
        base_dir = Path(sys.executable).parent
    else:
        base_dir = Path(__file__).resolve().parent

    dotenv_path = base_dir / ".env"
    #なければOSの環境変数だけ使う
    if dotenv_path.exists():
        load_dotenv(dotenv_path=dotenv_path,override =False)

load_env()


def ensure_env(base_dir: Path):
    env = base_dir / ".env"
    sample = base_dir / ".env.example"
    if not env.exists() and sample.exists():
        try:
            copyfile(sample, env)
            print(".env を作成しました。必要な値を編集してください。")
        except Exception as e:
            print(f".env の作成に失敗: {e}")

# 上の load_env と同じ base_dir 判定を使う
