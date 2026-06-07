"""認証フォーム。"""
from django.contrib.auth.forms import UserCreationForm

from accounts.models import User


class SignupForm(UserCreationForm):
    """サインアップフォーム。username + password のみの最小構成。

    TODO: パスワードリセット導入時に email フィールドを追加する。
    """

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username",)
