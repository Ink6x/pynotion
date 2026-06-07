# Page.owner と PageShare の追加 (Phase 1-A RBAC)。
#
# owner は非 NULL の FK。本番未デプロイ・開発 DB は作り直し運用のため
# 既存行は存在せず、one-off default は不要 (preserve_default=False で
# スキーマ上のデフォルトは残さない)。
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("pages", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="page",
            name="owner",
            field=models.ForeignKey(
                default=None,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="owned_pages",
                to=settings.AUTH_USER_MODEL,
            ),
            preserve_default=False,
        ),
        migrations.CreateModel(
            name="PageShare",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "role",
                    models.CharField(
                        choices=[
                            ("viewer", "閲覧者"),
                            ("commenter", "コメント可"),
                            ("editor", "編集者"),
                            ("full_access", "フルアクセス"),
                        ],
                        default="viewer",
                        max_length=16,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "page",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="shares",
                        to="pages.page",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="page_shares",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="pageshare",
            index=models.Index(fields=["user", "page"], name="pages_pages_user_id_51ae06_idx"),
        ),
        migrations.AddConstraint(
            model_name="pageshare",
            constraint=models.UniqueConstraint(
                fields=("page", "user"), name="unique_share_per_user"
            ),
        ),
        migrations.AddConstraint(
            model_name="pageshare",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    role__in=["viewer", "commenter", "editor", "full_access"]
                ),
                name="valid_share_role",
            ),
        ),
    ]
