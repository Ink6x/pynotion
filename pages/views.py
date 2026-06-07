"""HTML ビュー。"""
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie


@ensure_csrf_cookie
def index(request: HttpRequest) -> HttpResponse:
    """アプリシェル。データは JSON API から取得する SPA 構成。"""
    return render(request, "app.html")
