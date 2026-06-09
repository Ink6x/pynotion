"""Database / PropertySchema / DatabaseRow モデルと値正規化のテスト。"""
import pytest
from django.db import IntegrityError

from databases.models import Database, DatabaseRow, PropertySchema, normalize_row_values
from pages.models import Page

pytestmark = pytest.mark.django_db


@pytest.fixture
def database(user) -> Database:
    page = Page.objects.create_page(owner=user, title="タスク管理")
    return Database.objects.create(page=page)


@pytest.fixture
def status_prop(database) -> PropertySchema:
    return PropertySchema.objects.create_property(
        database=database,
        key="status",
        name="ステータス",
        type="select",
        config={"options": ["Todo", "Doing", "Done"]},
    )


def test_database_uses_page_for_rbac(database, user):
    # 権限は Page に委譲(owner は full_access)
    assert database.page.owner == user
    assert database.page.effective_role(user).value == "full_access"


def test_create_property_assigns_key_and_position(database):
    p1 = PropertySchema.objects.create_property(database=database, name="名前", type="text")
    p2 = PropertySchema.objects.create_property(database=database, name="数", type="number")
    assert p1.key  # 自動採番
    assert p1.position < p2.position  # fractional indexing で末尾追加


def test_create_property_rejects_unknown_type(database):
    with pytest.raises(ValueError, match="not a valid"):
        PropertySchema.objects.create_property(database=database, name="x", type="rating")


@pytest.mark.parametrize("reserved", ["isnull", "iregex", "icontains", "gt", "in"])
def test_create_property_rejects_reserved_key(database, reserved):
    # Django ルックアップ名を key にすると values__<key> がトランスフォームに化ける
    with pytest.raises(ValueError, match="予約語"):
        PropertySchema.objects.create_property(
            database=database, key=reserved, name="x", type="text"
        )


def test_property_key_unique_per_database(database):
    PropertySchema.objects.create_property(
        database=database, key="status", name="A", type="text"
    )
    with pytest.raises(IntegrityError):
        PropertySchema.objects.create_property(
            database=database, key="status", name="B", type="text"
        )


def test_create_row_normalizes_values(database, status_prop):
    PropertySchema.objects.create_property(
        database=database, key="title", name="名前", type="text"
    )
    row = DatabaseRow.objects.create_row(
        database=database, values={"status": "Doing", "title": "設計"}
    )
    assert row.values == {"status": "Doing", "title": "設計"}


def test_create_row_fills_missing_with_empty_values(database, status_prop):
    PropertySchema.objects.create_property(
        database=database, key="done", name="完了", type="checkbox"
    )
    row = DatabaseRow.objects.create_row(database=database, values={})
    # select の空は None、checkbox の空は False
    assert row.values == {"status": None, "done": False}


def test_create_row_drops_undefined_keys(database, status_prop):
    row = DatabaseRow.objects.create_row(
        database=database, values={"status": "Todo", "ghost": "捨てられる"}
    )
    assert "ghost" not in row.values
    assert row.values == {"status": "Todo"}


def test_create_row_rejects_invalid_value(database, status_prop):
    with pytest.raises(ValueError, match="選択肢"):
        DatabaseRow.objects.create_row(database=database, values={"status": "Nope"})


def test_rows_ordered_by_position(database, status_prop):
    r1 = DatabaseRow.objects.create_row(database=database, values={"status": "Todo"})
    r2 = DatabaseRow.objects.create_row(database=database, values={"status": "Doing"})
    rows = list(DatabaseRow.objects.filter(database=database))
    assert rows == [r1, r2]
    assert r1.position < r2.position


def test_create_row_after_inserts_between(database, status_prop):
    r1 = DatabaseRow.objects.create_row(database=database, values={"status": "Todo"})
    r3 = DatabaseRow.objects.create_row(database=database, values={"status": "Done"})
    r2 = DatabaseRow.objects.create_row(
        database=database, values={"status": "Doing"}, after=r1
    )
    rows = list(DatabaseRow.objects.filter(database=database))
    assert rows == [r1, r2, r3]


def test_normalize_row_values_rejects_non_dict(database):
    with pytest.raises(ValueError, match="オブジェクト"):
        normalize_row_values(database, ["not", "a", "dict"])


def test_str_representations(database, status_prop):
    row = DatabaseRow.objects.create_row(database=database, values={"status": "Todo"})
    assert "タスク管理" in str(database)
    assert "ステータス" in str(status_prop)
    assert str(row.id) in str(row)


def test_deleting_page_cascades_to_database(database):
    page = database.page
    db_id = database.id
    page.delete()
    assert not Database.objects.filter(id=db_id).exists()
