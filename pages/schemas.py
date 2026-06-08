"""django-ninja の入力スキーマ (pydantic)。

レスポンスは既存の ``serializers.py`` + 封筒 renderer が担うため、ここでは
**書き込み系のリクエストボディ**のみを型付けする。OpenAPI のリクエスト仕様は
これらから自動生成される。

部分更新 (PATCH / move) は「キーが送られたかどうか」で挙動が変わるため、
``model_fields_set`` で送信済みフィールドを判定する (None 値と未送信を区別する)。
"""
import uuid

from ninja import Schema


class PageCreateIn(Schema):
    title: str = ""
    icon: str = ""
    parent_id: uuid.UUID | None = None
    after_id: uuid.UUID | None = None


class PageUpdateIn(Schema):
    title: str | None = None
    icon: str | None = None


class PageMoveIn(Schema):
    # parent_id は「未送信なら現在の親を維持」「null 送信ならルートへ」を区別するため
    # model_fields_set で送信有無を見る。
    parent_id: uuid.UUID | None = None
    after_id: uuid.UUID | None = None


class BlockCreateIn(Schema):
    type: str = "paragraph"
    text: str = ""
    checked: bool = False
    parent_id: uuid.UUID | None = None
    after_id: uuid.UUID | None = None


class BlockUpdateIn(Schema):
    type: str | None = None
    text: str | None = None
    checked: bool | None = None
    collapsed: bool | None = None
    # 楽観ロック: クライアントが最後に見た version。送られた場合のみ競合検査する。
    version: int | None = None


class BlockMoveIn(Schema):
    # parent_id は「未送信なら現在の親を維持」「null 送信ならルートへ」を区別するため
    # model_fields_set で送信有無を見る (PageMoveIn と同じ規約)。
    parent_id: uuid.UUID | None = None
    after_id: uuid.UUID | None = None


class ShareCreateIn(Schema):
    username: str
    role: str
