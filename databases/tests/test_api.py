"""データベース API の統合テスト(認可・封筒・ビュー実行)。"""
import json

import pytest

from databases.models import Database, DatabaseRow, PropertySchema
from pages.models import Page, PageShare, Role
from pages.tests.helpers import patch_json, post_json

pytestmark = pytest.mark.django_db


def _data(response):
    body = json.loads(response.content)
    assert body["ok"] is True, body
    return body["data"]


@pytest.fixture
def page(user) -> Page:
    return Page.objects.create_page(owner=user, title="DB ページ")


@pytest.fixture
def database(page) -> Database:
    return Database.objects.create(page=page)


@pytest.fixture
def status_prop(database) -> PropertySchema:
    return PropertySchema.objects.create_property(
        database=database,
        key="status",
        name="状態",
        type="select",
        config={"options": ["Todo", "Doing", "Done"]},
    )


# --- データベース作成 -------------------------------------------------------


def test_create_database_from_page(authenticated_client, page):
    res = post_json(authenticated_client, "/api/databases/", {"page_id": str(page.id)})
    assert res.status_code == 201
    data = _data(res)
    assert data["database"]["page_id"] == str(page.id)


def test_create_database_rejects_duplicate(authenticated_client, database):
    res = post_json(
        authenticated_client, "/api/databases/", {"page_id": str(database.page_id)}
    )
    assert res.status_code == 400


def test_create_database_requires_login(client, page):
    res = post_json(client, "/api/databases/", {"page_id": str(page.id)})
    assert res.status_code == 401


def test_get_database_returns_schema_and_views(authenticated_client, database, status_prop):
    res = authenticated_client.get(f"/api/databases/{database.id}/")
    assert res.status_code == 200
    data = _data(res)
    assert len(data["database"]["properties"]) == 1
    assert data["database"]["properties"][0]["key"] == "status"


def test_get_database_hidden_from_non_member(client, database, other_user):
    client.force_login(other_user)
    res = client.get(f"/api/databases/{database.id}/")
    assert res.status_code == 404  # 存在を漏らさない


def test_page_detail_exposes_database_id(authenticated_client, database, page):
    # フロントが table/board を出すため、ページ詳細に database_id を載せる
    res = authenticated_client.get(f"/api/pages/{page.id}/")
    assert _data(res)["database_id"] == str(database.id)


def test_page_detail_database_id_null_for_plain_page(authenticated_client, user):
    plain = Page.objects.create_page(owner=user, title="ただのページ")
    res = authenticated_client.get(f"/api/pages/{plain.id}/")
    assert _data(res)["database_id"] is None


# --- プロパティ -------------------------------------------------------------


def test_create_and_update_property(authenticated_client, database):
    res = post_json(
        authenticated_client,
        f"/api/databases/{database.id}/properties/",
        {"name": "優先度", "type": "number"},
    )
    assert res.status_code == 201
    prop_id = _data(res)["property"]["id"]

    res = patch_json(
        authenticated_client,
        f"/api/databases/{database.id}/properties/{prop_id}/",
        {"name": "重要度"},
    )
    assert _data(res)["property"]["name"] == "重要度"


def test_create_property_rejects_bad_type(authenticated_client, database):
    res = post_json(
        authenticated_client,
        f"/api/databases/{database.id}/properties/",
        {"name": "x", "type": "rating"},
    )
    assert res.status_code == 400


def test_delete_property(authenticated_client, database, status_prop):
    res = authenticated_client.delete(
        f"/api/databases/{database.id}/properties/{status_prop.id}/"
    )
    assert res.status_code == 200
    assert not PropertySchema.objects.filter(pk=status_prop.id).exists()


# --- 行 ---------------------------------------------------------------------


def test_create_row_normalizes(authenticated_client, database, status_prop):
    res = post_json(
        authenticated_client,
        f"/api/databases/{database.id}/rows/",
        {"values": {"status": "Doing", "ghost": "x"}},
    )
    assert res.status_code == 201
    values = _data(res)["row"]["values"]
    assert values == {"status": "Doing"}  # 未定義キーは捨てられる


def test_create_row_rejects_invalid_value(authenticated_client, database, status_prop):
    res = post_json(
        authenticated_client,
        f"/api/databases/{database.id}/rows/",
        {"values": {"status": "Nope"}},
    )
    assert res.status_code == 400


def test_update_row_merges_partial(authenticated_client, database, status_prop):
    PropertySchema.objects.create_property(
        database=database, key="title", name="名前", type="text"
    )
    row = DatabaseRow.objects.create_row(
        database=database, values={"status": "Todo", "title": "設計"}
    )
    res = patch_json(
        authenticated_client,
        f"/api/databases/rows/{row.id}/",
        {"values": {"status": "Done"}},
    )
    values = _data(res)["row"]["values"]
    assert values == {"status": "Done", "title": "設計"}  # title は保持


def test_move_row_reorders(authenticated_client, database, status_prop):
    r1 = DatabaseRow.objects.create_row(database=database, values={"status": "Todo"})
    r2 = DatabaseRow.objects.create_row(database=database, values={"status": "Doing"})
    # r1 を r2 の直後へ
    res = post_json(
        authenticated_client,
        f"/api/databases/rows/{r1.id}/move/",
        {"after_id": str(r2.id)},
    )
    assert res.status_code == 200
    order = list(DatabaseRow.objects.filter(database=database).values_list("id", flat=True))
    assert order == [r2.id, r1.id]


def test_move_row_bad_after_400(authenticated_client, database, status_prop):
    row = DatabaseRow.objects.create_row(database=database, values={})
    res = post_json(
        authenticated_client,
        f"/api/databases/rows/{row.id}/move/",
        {"after_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert res.status_code == 400


def test_delete_row(authenticated_client, database, status_prop):
    row = DatabaseRow.objects.create_row(database=database, values={"status": "Todo"})
    res = authenticated_client.delete(f"/api/databases/rows/{row.id}/")
    assert res.status_code == 200
    assert not DatabaseRow.objects.filter(pk=row.id).exists()


def test_move_row_viewer_forbidden(client, database, status_prop, other_user):
    PageShare.objects.create(page=database.page, user=other_user, role=Role.VIEWER)
    row = DatabaseRow.objects.create_row(database=database, values={})
    client.force_login(other_user)
    res = post_json(client, f"/api/databases/rows/{row.id}/move/", {})
    assert res.status_code == 403


def test_move_row_non_member_404(client, database, status_prop, other_user):
    row = DatabaseRow.objects.create_row(database=database, values={})
    client.force_login(other_user)
    res = post_json(client, f"/api/databases/rows/{row.id}/move/", {})
    assert res.status_code == 404  # 存在を漏らさない


# --- ビュー(table / board)-------------------------------------------------


def test_table_view_applies_filter_and_sort(authenticated_client, database, status_prop):
    PropertySchema.objects.create_property(
        database=database, key="age", name="数", type="number"
    )
    for s, a in [("Done", 30), ("Todo", 10), ("Todo", 20)]:
        DatabaseRow.objects.create_row(database=database, values={"status": s, "age": a})
    res = post_json(
        authenticated_client,
        f"/api/databases/{database.id}/views/",
        {
            "type": "table",
            "filters": {"property": "status", "op": "eq", "value": "Todo"},
            "sorts": [{"property": "age", "direction": "desc"}],
        },
    )
    view_id = _data(res)["view"]["id"]
    res = authenticated_client.get(f"/api/databases/views/{view_id}/rows/")
    ages = [r["values"]["age"] for r in _data(res)["rows"]]
    assert ages == [20, 10]  # Todo のみ、age 降順


def test_board_view_groups_by_select(authenticated_client, database, status_prop):
    for s in ["Todo", "Todo", "Done"]:
        DatabaseRow.objects.create_row(database=database, values={"status": s})
    res = post_json(
        authenticated_client,
        f"/api/databases/{database.id}/views/",
        {"type": "board", "group_by": "status"},
    )
    view_id = _data(res)["view"]["id"]
    res = authenticated_client.get(f"/api/databases/views/{view_id}/rows/")
    groups = {g["value"]: len(g["rows"]) for g in _data(res)["groups"]}
    # options 順に空レーンも含む + 未設定(None)
    assert groups["Todo"] == 2
    assert groups["Done"] == 1
    assert groups["Doing"] == 0
    assert None in groups


def test_create_view_rejects_invalid_filter_at_write_time(
    authenticated_client, database, status_prop
):
    # 壊れたフィルタは保存時点で 400(stored-bomb を防ぐ)
    res = post_json(
        authenticated_client,
        f"/api/databases/{database.id}/views/",
        {"type": "table", "filters": {"property": "ghost", "op": "eq", "value": 1}},
    )
    assert res.status_code == 400


def test_create_board_rejects_unknown_group_by(authenticated_client, database, status_prop):
    res = post_json(
        authenticated_client,
        f"/api/databases/{database.id}/views/",
        {"type": "board", "group_by": "ghost"},
    )
    assert res.status_code == 400


def test_update_view_rejects_invalid_filter(authenticated_client, database, status_prop):
    res = post_json(
        authenticated_client, f"/api/databases/{database.id}/views/", {"name": "A"}
    )
    view_id = _data(res)["view"]["id"]
    res = patch_json(
        authenticated_client,
        f"/api/databases/views/{view_id}/",
        {"filters": {"property": "ghost", "op": "eq", "value": 1}},
    )
    assert res.status_code == 400


def test_update_and_delete_view(authenticated_client, database):
    res = post_json(
        authenticated_client, f"/api/databases/{database.id}/views/", {"name": "A"}
    )
    view_id = _data(res)["view"]["id"]
    res = patch_json(
        authenticated_client, f"/api/databases/views/{view_id}/", {"name": "B"}
    )
    assert _data(res)["view"]["name"] == "B"
    res = authenticated_client.delete(f"/api/databases/views/{view_id}/")
    assert res.status_code == 200


# --- 認可 -------------------------------------------------------------------


def test_viewer_cannot_write(client, database, status_prop, other_user):
    PageShare.objects.create(page=database.page, user=other_user, role=Role.VIEWER)
    client.force_login(other_user)
    # viewer は読める
    assert client.get(f"/api/databases/{database.id}/").status_code == 200
    # が書けない(403)
    res = post_json(
        client, f"/api/databases/{database.id}/rows/", {"values": {"status": "Todo"}}
    )
    assert res.status_code == 403


def test_editor_can_write(client, database, status_prop, other_user):
    PageShare.objects.create(page=database.page, user=other_user, role=Role.EDITOR)
    client.force_login(other_user)
    res = post_json(
        client, f"/api/databases/{database.id}/rows/", {"values": {"status": "Done"}}
    )
    assert res.status_code == 201


# --- 404 / エッジケース -----------------------------------------------------

_MISSING = "00000000-0000-0000-0000-000000000000"


def test_create_database_missing_page_404(authenticated_client):
    res = post_json(authenticated_client, "/api/databases/", {"page_id": _MISSING})
    assert res.status_code == 404


def test_get_missing_database_404(authenticated_client):
    res = authenticated_client.get(f"/api/databases/{_MISSING}/")
    assert res.status_code == 404


def test_update_missing_property_404(authenticated_client, database):
    res = patch_json(
        authenticated_client,
        f"/api/databases/{database.id}/properties/{_MISSING}/",
        {"name": "x"},
    )
    assert res.status_code == 404


def test_update_missing_row_404(authenticated_client):
    res = patch_json(
        authenticated_client, f"/api/databases/rows/{_MISSING}/", {"values": {}}
    )
    assert res.status_code == 404


def test_delete_missing_view_404(authenticated_client):
    res = authenticated_client.delete(f"/api/databases/views/{_MISSING}/")
    assert res.status_code == 404


def test_create_row_after_inserts_between(authenticated_client, database, status_prop):
    r1 = DatabaseRow.objects.create_row(database=database, values={"status": "Todo"})
    DatabaseRow.objects.create_row(database=database, values={"status": "Done"})
    res = post_json(
        authenticated_client,
        f"/api/databases/{database.id}/rows/",
        {"values": {"status": "Doing"}, "after_id": str(r1.id)},
    )
    assert res.status_code == 201
    positions = list(
        DatabaseRow.objects.filter(database=database).values_list("position", flat=True)
    )
    assert positions == sorted(positions)


def test_create_row_bad_after_id_400(authenticated_client, database, status_prop):
    res = post_json(
        authenticated_client,
        f"/api/databases/{database.id}/rows/",
        {"values": {"status": "Todo"}, "after_id": _MISSING},
    )
    assert res.status_code == 400


def test_update_view_all_fields(authenticated_client, database, status_prop):
    res = post_json(
        authenticated_client, f"/api/databases/{database.id}/views/", {"name": "A"}
    )
    view_id = _data(res)["view"]["id"]
    res = patch_json(
        authenticated_client,
        f"/api/databases/views/{view_id}/",
        {
            "type": "board",
            "filters": {"property": "status", "op": "eq", "value": "Done"},
            "sorts": [{"property": "status", "direction": "asc"}],
            "group_by": "status",
        },
    )
    view = _data(res)["view"]
    assert view["type"] == "board"
    assert view["group_by"] == "status"


def test_create_view_rejects_bad_type(authenticated_client, database):
    res = post_json(
        authenticated_client,
        f"/api/databases/{database.id}/views/",
        {"type": "calendar"},
    )
    assert res.status_code == 400


def test_update_property_config(authenticated_client, database, status_prop):
    res = patch_json(
        authenticated_client,
        f"/api/databases/{database.id}/properties/{status_prop.id}/",
        {"config": {"options": ["A", "B"]}},
    )
    assert _data(res)["property"]["config"] == {"options": ["A", "B"]}


def test_row_hidden_from_non_member_404(client, database, status_prop, other_user):
    row = DatabaseRow.objects.create_row(database=database, values={"status": "Todo"})
    client.force_login(other_user)  # 共有なし
    res = patch_json(client, f"/api/databases/rows/{row.id}/", {"values": {}})
    assert res.status_code == 404  # 存在を漏らさない


def test_view_hidden_from_non_member_404(client, database, other_user):
    from databases.models import DatabaseView

    view = DatabaseView.objects.create(database=database, name="V")
    client.force_login(other_user)  # 共有なし
    res = patch_json(client, f"/api/databases/views/{view.id}/", {"name": "X"})
    assert res.status_code == 404
