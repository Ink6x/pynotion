"""認証ビュー (サインアップ / ログイン / ログアウト)。

ログアウトは django.contrib.auth.views.LogoutView をそのまま使う
(urls.py 参照。LOGOUT_REDIRECT_URL でリダイレクト)。
"""
from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from accounts.forms import SignupForm


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    redirect_authenticated_user = True


def signup(request: HttpRequest) -> HttpResponse:
    """サインアップ。成功時は自動ログインしてアプリへ。

    セッション固定対策は login() 内部のキーローテーションに委ねる。
    """
    if request.user.is_authenticated:
        return redirect(settings.LOGIN_REDIRECT_URL)
    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect(settings.LOGIN_REDIRECT_URL)
    else:
        form = SignupForm()
    return render(request, "accounts/signup.html", {"form": form})
