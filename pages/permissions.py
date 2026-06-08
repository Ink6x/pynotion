"""ページ認可 — ロール検査ヘルパー。

方針:
- アクセス権が全く無いページは 404 (存在を漏らさない)
- ロール不足 (viewer が編集など) は PermissionError → 403
- 未認証は API 層 (認証) が 401 を返すため、ここでは認証済み前提

API オペレーション (``pages.api``) はこの ``check_page_role`` を直接呼んで
認可する。
"""
from .models import Page, Role, role_satisfies

NOT_FOUND_MESSAGE = "ページが見つかりません"


def check_page_role(page: Page, user, min_role: Role) -> None:
    """user が page に min_role 以上を持たなければ例外を送出する。

    アクセス権ゼロは LookupError (呼び出し側で 404 に変換)、
    ロール不足は PermissionError (API 層が 403 に変換)。
    """
    role = page.effective_role(user)
    if role is None:
        raise LookupError(NOT_FOUND_MESSAGE)
    if not role_satisfies(role, min_role):
        raise PermissionError("この操作を行う権限がありません")
