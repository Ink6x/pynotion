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


class Webhook(models.Model):
    """ページの変更イベントを外部 URL へ HMAC 署名付きで通知する登録。

    URL は信頼境界。共有(full_access)を持つユーザーだけが登録できる。``secret`` は
    配信ボディの HMAC-SHA256 署名に使い、受信側が改竄検知できるようにする。
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name="webhooks")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="webhooks",
    )
    url = models.URLField(max_length=2048)
    secret = models.CharField(max_length=64)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["page", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"Webhook({self.url})"


class WebhookDelivery(models.Model):
    """1 回の配信試行の記録。``(webhook, event_id)`` で冪等性を担保する。

    同じイベントを二重配信しないよう event_id を一意制約にし、``done`` 済みなら
    再送しない。失敗時は指数バックオフでリトライした回数を ``attempts`` に持つ。
    """

    class Status(models.TextChoices):
        PENDING = "pending", "待機中"
        DONE = "done", "成功"
        FAILED = "failed", "失敗"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    webhook = models.ForeignKey(
        Webhook, on_delete=models.CASCADE, related_name="deliveries"
    )
    event_id = models.UUIDField()
    event = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    attempts = models.PositiveIntegerField(default=0)
    last_status_code = models.PositiveIntegerField(null=True, blank=True)
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["webhook", "event_id"], name="unique_delivery_per_event"
            ),
        ]

    def __str__(self) -> str:
        return f"WebhookDelivery({self.event}, {self.status})"
