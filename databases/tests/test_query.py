"""宣言的フィルタ / ソート → Q 変換の安全性と正しさのテスト。

セキュリティの肝(演算子ホワイトリスト・スキーマ照合・ORM 経由)を、
SQL インジェクション試行を含めて固定する。
"""
import pytest

from databases.models import (
    Database,
    DatabaseRow,
    DatabaseView,
    PropertySchema,
    ViewType,
)
from databases.query import (
    build_filter_q,
    build_order_by,
    rows_for_view,
    validate_view_spec,
)
from pages.models import Page

pytestmark = pytest.mark.django_db


@pytest.fixture
def database(user) -> Database:
    page = Page.objects.create_page(owner=user, title="タスク")
    db = Database.objects.create(page=page)
    PropertySchema.objects.create_property(
        database=db, key="title", name="名前", type="text"
    )
    PropertySchema.objects.create_property(
        database=db,
        key="status",
        name="状態",
        type="select",
        config={"options": ["Todo", "Doing", "Done"]},
    )
    PropertySchema.objects.create_property(
        database=db, key="age", name="数", type="number"
    )
    PropertySchema.objects.create_property(
        database=db, key="done", name="完了", type="checkbox"
    )
    return db


@pytest.fixture
def rows(database):
    data = [
        {"title": "設計", "status": "Done", "age": 30, "done": True},
        {"title": "実装", "status": "Doing", "age": 10, "done": False},
        {"title": "レビュー", "status": "Todo", "age": 20, "done": False},
    ]
    return [DatabaseRow.objects.create_row(database=database, values=v) for v in data]


def _titles(qs):
    # フィルタ結果は順序非依存なので集合で比較する(和文の並びに依存しない)。
    return {r.values["title"] for r in qs}


# --- 正しさ -----------------------------------------------------------------


def test_eq_filter(database, rows):
    q = build_filter_q(database, {"property": "status", "op": "eq", "value": "Done"})
    assert _titles(database.rows.filter(q)) == {"設計"}


def test_neq_filter(database, rows):
    q = build_filter_q(database, {"property": "status", "op": "neq", "value": "Done"})
    assert _titles(database.rows.filter(q)) == {"実装", "レビュー"}


def test_contains_filter(database, rows):
    q = build_filter_q(database, {"property": "title", "op": "contains", "value": "ュ"})
    assert _titles(database.rows.filter(q)) == {"レビュー"}


def test_numeric_comparison(database, rows):
    q = build_filter_q(database, {"property": "age", "op": "gte", "value": 20})
    assert _titles(database.rows.filter(q)) == {"設計", "レビュー"}


def test_checkbox_eq(database, rows):
    q = build_filter_q(database, {"property": "done", "op": "eq", "value": False})
    assert _titles(database.rows.filter(q)) == {"レビュー", "実装"}


def test_in_filter(database, rows):
    q = build_filter_q(
        database, {"property": "status", "op": "in", "value": ["Todo", "Doing"]}
    )
    assert _titles(database.rows.filter(q)) == {"レビュー", "実装"}


def test_not_contains_filter(database, rows):
    q = build_filter_q(
        database, {"property": "title", "op": "not_contains", "value": "ュ"}
    )
    assert _titles(database.rows.filter(q)) == {"設計", "実装"}


def test_lt_and_lte(database, rows):
    lt = build_filter_q(database, {"property": "age", "op": "lt", "value": 20})
    lte = build_filter_q(database, {"property": "age", "op": "lte", "value": 20})
    assert _titles(database.rows.filter(lt)) == {"実装"}
    assert _titles(database.rows.filter(lte)) == {"実装", "レビュー"}


def test_view_str(database):
    view = DatabaseView.objects.create(database=database, name="未完", type="board")
    assert "未完" in str(view)
    assert "board" in str(view)


def test_group_rows_by_select_with_dict_options(user):
    from databases.query import group_rows

    page = Page.objects.create_page(owner=user)
    db = Database.objects.create(page=page)
    PropertySchema.objects.create_property(
        database=db,
        key="prio",
        name="優先度",
        type="select",
        config={"options": [{"name": "Low"}, {"name": "High"}]},  # dict 形式の options
    )
    DatabaseRow.objects.create_row(database=db, values={"prio": "High"})
    DatabaseRow.objects.create_row(database=db, values={})  # 未設定
    view = DatabaseView.objects.create(database=db, type=ViewType.BOARD, group_by="prio")
    groups = {g["value"]: len(g["rows"]) for g in group_rows(view, list(db.rows.all()))}
    assert groups == {"Low": 0, "High": 1, None: 1}


def test_group_rows_by_multi_select(user):
    from databases.query import group_rows

    page = Page.objects.create_page(owner=user)
    db = Database.objects.create(page=page)
    PropertySchema.objects.create_property(
        database=db,
        key="tags",
        name="タグ",
        type="multi_select",
        config={"options": ["a", "b", "c"]},
    )
    DatabaseRow.objects.create_row(database=db, values={"tags": ["a", "b"]})
    DatabaseRow.objects.create_row(database=db, values={"tags": []})  # 未設定
    view = DatabaseView.objects.create(database=db, type=ViewType.BOARD, group_by="tags")
    groups = {g["value"]: len(g["rows"]) for g in group_rows(view, list(db.rows.all()))}
    # 1 行が a と b の両グループに属し、空配列は未設定へ
    assert groups["a"] == 1
    assert groups["b"] == 1
    assert groups[None] == 1


def test_group_rows_invalid_group_by_rejected(database):
    from databases.query import group_rows

    view = DatabaseView.objects.create(database=database, type=ViewType.BOARD, group_by="")
    with pytest.raises(ValueError, match="group_by"):
        group_rows(view, [])


def test_and_combination(database, rows):
    q = build_filter_q(
        database,
        {
            "and": [
                {"property": "done", "op": "eq", "value": False},
                {"property": "age", "op": "gt", "value": 15},
            ]
        },
    )
    assert _titles(database.rows.filter(q)) == {"レビュー"}


def test_or_combination(database, rows):
    q = build_filter_q(
        database,
        {
            "or": [
                {"property": "status", "op": "eq", "value": "Done"},
                {"property": "status", "op": "eq", "value": "Todo"},
            ]
        },
    )
    assert _titles(database.rows.filter(q)) == {"設計", "レビュー"}


def test_not_combination(database, rows):
    q = build_filter_q(
        database, {"not": {"property": "status", "op": "eq", "value": "Done"}}
    )
    assert _titles(database.rows.filter(q)) == {"実装", "レビュー"}


def test_empty_filter_matches_all(database, rows):
    assert database.rows.filter(build_filter_q(database, {})).count() == 3
    assert database.rows.filter(build_filter_q(database, None)).count() == 3


def test_is_empty_and_not_empty(database):
    PropertySchema.objects.create_property(
        database=database, key="note", name="メモ", type="text"
    )
    DatabaseRow.objects.create_row(database=database, values={"note": ""})
    DatabaseRow.objects.create_row(database=database, values={"note": "あり"})
    empty = build_filter_q(database, {"property": "note", "op": "is_empty"})
    not_empty = build_filter_q(database, {"property": "note", "op": "is_not_empty"})
    assert database.rows.filter(empty).count() == 1
    assert database.rows.filter(not_empty).count() == 1


def test_is_empty_is_type_aware_for_checkbox(database):
    # checkbox の空値は False。is_empty が未チェック行を正しく拾う(型認識)。
    DatabaseRow.objects.create_row(database=database, values={"done": False})
    DatabaseRow.objects.create_row(database=database, values={"done": True})
    empty = build_filter_q(database, {"property": "done", "op": "is_empty"})
    not_empty = build_filter_q(database, {"property": "done", "op": "is_not_empty"})
    assert database.rows.filter(empty).count() == 1
    assert database.rows.filter(not_empty).count() == 1


def test_deeply_nested_filter_rejected(database):
    # {"not": {"not": ...}} を深くネストしても RecursionError ではなく ValueError
    spec = {"property": "age", "op": "eq", "value": 1}
    for _ in range(40):
        spec = {"not": spec}
    with pytest.raises(ValueError, match="深すぎます"):
        build_filter_q(database, spec)


def test_in_rejects_non_scalar_elements(database):
    with pytest.raises(ValueError, match="スカラ"):
        build_filter_q(
            database, {"property": "status", "op": "in", "value": [{"evil": 1}]}
        )


# --- ソート -----------------------------------------------------------------


def test_order_by_asc(database, rows):
    order = build_order_by(database, [{"property": "age", "direction": "asc"}])
    got = [r.values["age"] for r in database.rows.order_by(*order)]
    assert got == [10, 20, 30]


def test_order_by_desc(database, rows):
    order = build_order_by(database, [{"property": "age", "direction": "desc"}])
    got = [r.values["age"] for r in database.rows.order_by(*order)]
    assert got == [30, 20, 10]


def test_order_by_defaults_to_position(database):
    assert build_order_by(database, []) == ["position"]
    assert build_order_by(database, None) == ["position"]


def test_validate_view_spec_accepts_valid(database):
    validate_view_spec(
        database,
        filters={"property": "status", "op": "eq", "value": "Done"},
        sorts=[{"property": "age", "direction": "asc"}],
        group_by="status",
    )  # 例外が出なければ OK


def test_validate_view_spec_rejects_bad_filter(database):
    with pytest.raises(ValueError, match="未知のプロパティ"):
        validate_view_spec(
            database,
            filters={"property": "ghost", "op": "eq", "value": 1},
            sorts=[],
            group_by="",
        )


def test_validate_view_spec_rejects_unknown_group_by(database):
    with pytest.raises(ValueError, match="group_by"):
        validate_view_spec(database, filters={}, sorts=[], group_by="ghost")


def test_rows_for_view_applies_filter_and_sort(database, rows):
    view = DatabaseView.objects.create(
        database=database,
        type=ViewType.TABLE,
        filters={"property": "done", "op": "eq", "value": False},
        sorts=[{"property": "age", "direction": "desc"}],
    )
    got = [r.values["title"] for r in rows_for_view(view)]
    assert got == ["レビュー", "実装"]  # age 20, 10 の降順


# --- セキュリティ / 入力検証 ------------------------------------------------


def test_unknown_property_rejected(database):
    with pytest.raises(ValueError, match="未知のプロパティ"):
        build_filter_q(database, {"property": "secret", "op": "eq", "value": 1})


def test_unknown_operator_rejected(database):
    with pytest.raises(ValueError, match="許可されていない演算子"):
        build_filter_q(database, {"property": "age", "op": "exec", "value": 1})


def test_sql_injection_in_property_name_rejected(database):
    # 列名に SQL を仕込んでもスキーマ照合で弾かれる(注入不可)
    with pytest.raises(ValueError, match="未知のプロパティ"):
        build_filter_q(
            database,
            {"property": "age) OR 1=1 --", "op": "eq", "value": 1},
        )


def test_sql_injection_in_value_is_parameterized(database, rows):
    # 値に SQL を入れても文字列として安全に比較されるだけ(注入されない)
    q = build_filter_q(
        database,
        {"property": "title", "op": "eq", "value": "'; DROP TABLE databases_databaserow; --"},
    )
    assert database.rows.filter(q).count() == 0
    # テーブルは健在
    assert database.rows.count() == 3


def test_non_scalar_value_rejected(database):
    with pytest.raises(ValueError, match="スカラ"):
        build_filter_q(
            database, {"property": "age", "op": "eq", "value": {"nested": "obj"}}
        )


def test_in_requires_list(database):
    with pytest.raises(ValueError, match="配列"):
        build_filter_q(database, {"property": "status", "op": "in", "value": "Todo"})


def test_and_must_be_nonempty_list(database):
    with pytest.raises(ValueError, match="非空の配列"):
        build_filter_q(database, {"and": []})


def test_and_must_be_single_key(database):
    with pytest.raises(ValueError, match="単独のキー"):
        build_filter_q(
            database,
            {"and": [{"property": "age", "op": "eq", "value": 1}], "or": []},
        )


def test_not_must_be_single_key(database):
    with pytest.raises(ValueError, match="単独のキー"):
        build_filter_q(
            database,
            {"not": {"property": "age", "op": "eq", "value": 1}, "extra": 1},
        )


def test_filter_must_be_dict(database):
    with pytest.raises(ValueError, match="object"):
        build_filter_q(database, "not a dict")


def test_order_by_unknown_property_rejected(database):
    with pytest.raises(ValueError, match="未知のプロパティ"):
        build_order_by(database, [{"property": "ghost", "direction": "asc"}])


def test_order_by_bad_direction_rejected(database):
    with pytest.raises(ValueError, match="direction"):
        build_order_by(database, [{"property": "age", "direction": "sideways"}])


def test_order_by_must_be_list(database):
    with pytest.raises(ValueError, match="配列"):
        build_order_by(database, {"property": "age"})


def test_order_by_item_must_be_dict(database):
    with pytest.raises(ValueError, match="object"):
        build_order_by(database, ["age"])


def test_property_key_with_lookup_separator_rejected(database):
    # `__` を含む key はトランスフォーム注入になりうるので作成時点で弾く
    with pytest.raises(ValueError, match="key"):
        PropertySchema.objects.create_property(
            database=database, key="evil__gt", name="x", type="number"
        )
