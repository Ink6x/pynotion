"""エクスポートジョブ。

ページを Markdown 等へ書き出す非同期ジョブの状態を持つ。生成自体は ``tasks`` が
行い、本番は RQ ワーカーが、開発/テストは同期実行する(``queue`` 参照)。
"""
import uuid

from django.conf import settings
from django.db import models

from pages.models import Page


class Export(models.Model):
    class Format(models.TextChoices):
        MARKDOWN = "markdown", "Markdown"

    class Status(models.TextChoices):
        PENDING = "pending", "待機中"
        RUNNING = "running", "実行中"
        DONE = "done", "完了"
        FAILED = "failed", "失敗"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name="exports")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="exports",
    )
    format = models.CharField(
        max_length=16, choices=Format.choices, default=Format.MARKDOWN
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    content = models.TextField(blank=True, default="")
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["page", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"Export({self.format}, {self.status})"
