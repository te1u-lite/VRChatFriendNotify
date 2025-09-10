from dotenv import load_dotenv
import os

import vrchatapi
from vrchatapi.api import authentication_api
from vrchatapi.exceptions import UnauthorizedException
from vrchatapi.models.two_factor_auth_code import TwoFactorAuthCode
from vrchatapi.models.two_factor_email_code import TwoFactorEmailCode

load_dotenv()

configurarion = vrchatapi.Configuration(
    username = os.getenv("VRCHAT_USERNAME"),
    password = os.getenv("VRCHAT_PASSWORD"),
)
api_client = vrchatapi.ApiClient(configurarion)

api_client.user_agent =f"Mozilla/5.0 {configurarion.username}"
auth_api = authentication_api.AuthenticationApi(api_client)
try:
    current_user = auth_api.get_current_user()
#初回は2FAが有効になっているため、2FAのコードを入力する
except UnauthorizedException as e:
    if e.status == 200:
        auth_api.verify2_fa_email_code(two_factor_email_code=TwoFactorEmailCode(input("Email 2FA Code: ")))
    elif "2 Factor Authentication" in e.reason:
        auth_api.verify2_fa(two_factor_auth_code=TwoFactorAuthCode(input("2FA Code: ")))
    else:
        print("Exception when calling API: %s\n",e)
except vrchatapi.ApiException as e:
    print("Exception when calling API: %s\n",e)

#ユーザ情報取得
from vrchatapi.api import users_api
user_id = os.getenv("VRCHAT_USERID")
users_api = users_api.UsersApi(api_client)
user = users_api.get_user(user_id=user_id)
print(user)