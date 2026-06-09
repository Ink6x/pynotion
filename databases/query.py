"""宣言的フィルタ / ソート JSON を Django ORM の Q / order_by へ安全に変換する。

設計(`docs/plan/02-architecture.md` D 節、判断記録 #4):

スキーマレスな行(``DatabaseRow.values`` JSONB)に対する検索条件を、ユーザーが
保存した **宣言的 JSON** から組み立てる。これは「動的クエリ」であり SQL
インジェクションの温床になりやすいため、次の防御で安全性を担保する:

1. **演算子はホワイトリスト**(``_OPERATORS`` にある op しか通さない)
2. **フィールドはスキーマ照合**(``database`` に実在する property key のみ。
   key 自体も英数字+`_` に制限し Django 予約語も禁止 = `values__<key>` への注入不可)
3. **値は ORM 経由のみ**でクエリへ渡す(生 SQL を一切組み立てない = 常にパラメータ化)
4. **ネスト深さ / 配列要素を制限**(深い再帰や非スカラ値による DoS・500 を防ぐ)

入力はすべて信頼境界。不正な構造・未知の演算子・未知のプロパティ・非スカラ値は
``ValueError`` を投げる(API 層で 400 に変換)。
"""
from __future__ import annotations

from collections.abc import Callable

from django.db.models import Q

from .properties import _option_names, empty_value

# フィルタの論理ネストの最大深さ。深い ``{"not": {"not": ...}}`` による
# RecursionError(→500)を防ぐ。
MAX_FILTER_DEPTH = 25

# 演算子 → Q ビルダ。引数は (prop: PropertySchema, value)。ここに無い op は弾く。
_OPERATORS: dict[str, Callable[[object, object], Q]] = {}


def _op(name: str):
    def register(fn: Callable[[object, object], Q]) -> Callable[[object, object], Q]:
        _OPERATORS[name] = fn
        return fn

    return register


def _field(key: str) -> str:
    return f"values__{key}"


@_op("eq")
def _eq(prop, value) -> Q:
    return Q(**{_field(prop.key): value})


@_op("neq")
def _neq(prop, value) -> Q:
    return ~Q(**{_field(prop.key): value})


@_op("contains")
def _contains(prop, value) -> Q:
    return Q(**{f"{_field(prop.key)}__icontains": value})


@_op("not_contains")
def _not_contains(prop, value) -> Q:
    return ~Q(**{f"{_field(prop.key)}__icontains": value})


@_op("gt")
def _gt(prop, value) -> Q:
    return Q(**{f"{_field(prop.key)}__gt": value})


@_op("gte")
def _gte(prop, value) -> Q:
    return Q(**{f"{_field(prop.key)}__gte": value})


@_op("lt")
def _lt(prop, value) -> Q:
    return Q(**{f"{_field(prop.key)}__lt": value})


@_op("lte")
def _lte(prop, value) -> Q:
    return Q(**{f"{_field(prop.key)}__lte": value})


@_op("in")
def _in(prop, value) -> Q:
    if not isinstance(value, list):
        raise ValueError("in 演算子の値は配列で指定してください")
    for item in value:
        if not isinstance(item, _SCALAR):
            raise ValueError(f"in 演算子の配列要素はスカラで指定してください: {item!r}")
    return Q(**{f"{_field(prop.key)}__in": value})


def _is_empty_q(prop) -> Q:
    """その型の「空値」または NULL に一致する Q。

    空値は型ごとに異なる(text="" / checkbox=False / select=None /
    multi_select・relation=[] / number・date=None)ため ``empty_value`` を使う。
    これで checkbox の未チェック(False)も is_empty で正しく拾える。
    """
    field = _field(prop.key)
    empty = empty_value(prop.type)
    q = Q(**{field: None})
    if empty is not None:
        q |= Q(**{field: empty})
    return q


@_op("is_empty")
def _is_empty(prop, value) -> Q:
    return _is_empty_q(prop)


@_op("is_not_empty")
def _is_not_empty(prop, value) -> Q:
    return ~_is_empty_q(prop)


# 値として許すスカラ。dict や任意オブジェクトは弾く(in は要素も検証)。
_SCALAR = (str, int, float, bool, type(None))


def _validate_leaf_value(op: str, value) -> None:
    if op in ("is_empty", "is_not_empty", "in"):
        return  # is_empty は値不要、in は _in が要素を検証する
    if not isinstance(value, _SCALAR):
        raise ValueError(f"フィルタ値はスカラで指定してください: {value!r}")


def build_filter_q(database, spec, *, schema: dict | None = None, _depth: int = 0) -> Q:
    """フィルタ JSON を Q へ変換する(再帰)。

    受け付ける形:
    - ``{}`` / ``None`` → すべて一致(``Q()``)
    - ``{"and": [spec, ...]}`` / ``{"or": [spec, ...]}`` / ``{"not": spec}``
    - 葉 ``{"property": key, "op": name, "value": v}``
    """
    if _depth > MAX_FILTER_DEPTH:
        raise ValueError("フィルタのネストが深すぎます")
    if not spec:
        return Q()
    if not isinstance(spec, dict):
        raise ValueError("フィルタは object で指定してください")
    if schema is None:
        schema = database.schema_map()

    if "and" in spec or "or" in spec:
        if len(spec) != 1:
            raise ValueError("and / or は単独のキーで指定してください")
        connector = "and" if "and" in spec else "or"
        children = spec[connector]
        if not isinstance(children, list) or not children:
            raise ValueError(f"{connector} は非空の配列で指定してください")
        combined: Q | None = None
        for child in children:
            q = build_filter_q(database, child, schema=schema, _depth=_depth + 1)
            if combined is None:
                combined = q
            elif connector == "and":
                combined &= q
            else:
                combined |= q
        return combined

    if "not" in spec:
        if len(spec) != 1:
            raise ValueError("not は単独のキーで指定してください")
        return ~build_filter_q(database, spec["not"], schema=schema, _depth=_depth + 1)

    return _build_leaf(schema, spec)


def _build_leaf(schema: dict, spec: dict) -> Q:
    prop = spec.get("property")
    op = spec.get("op")
    value = spec.get("value")

    if prop not in schema:
        # 未定義プロパティでの絞り込みは拒否(存在しない列名の注入を防ぐ)
        raise ValueError(f"未知のプロパティです: {prop!r}")
    if op not in _OPERATORS:
        raise ValueError(f"許可されていない演算子です: {op!r}")
    _validate_leaf_value(op, value)
    return _OPERATORS[op](schema[prop], value)


def build_order_by(database, sorts, *, schema: dict | None = None) -> list[str]:
    """ソート JSON を ``order_by`` 引数列へ変換する。

    ``[{"property": key, "direction": "asc"|"desc"}, ...]``。
    末尾に安定ソート用の ``position`` を必ず付ける。
    """
    if not sorts:
        return ["position"]
    if not isinstance(sorts, list):
        raise ValueError("sorts は配列で指定してください")
    if schema is None:
        schema = database.schema_map()
    order: list[str] = []
    for item in sorts:
        if not isinstance(item, dict):
            raise ValueError("sort は object で指定してください")
        prop = item.get("property")
        direction = item.get("direction", "asc")
        if prop not in schema:
            raise ValueError(f"未知のプロパティです: {prop!r}")
        if direction not in ("asc", "desc"):
            raise ValueError(f"direction は asc / desc で指定してください: {direction!r}")
        prefix = "-" if direction == "desc" else ""
        order.append(f"{prefix}{_field(schema[prop].key)}")
    order.append("position")  # 同値の安定化
    return order


def validate_view_spec(database, *, filters, sorts, group_by: str) -> None:
    """ビューの宣言的 JSON を「保存前」に検証する(不正なら ValueError)。

    保存時に弾くことで、壊れたビューが保存され閲覧者の GET が毎回 400/500 になる
    「stored-bomb」状態を防ぐ。クエリ自体は実行しない(構築のみで検証)。
    """
    schema = database.schema_map()
    build_filter_q(database, filters, schema=schema)
    build_order_by(database, sorts, schema=schema)
    if group_by and group_by not in schema:
        raise ValueError(f"group_by に存在しないプロパティを指定してください: {group_by!r}")


def rows_for_view(view) -> list:
    """ビューの filters / sorts を適用した ``DatabaseRow`` のリストを返す。"""
    database = view.database
    schema = database.schema_map()  # 1 回だけ引いて使い回す(N+1 回避)
    q = build_filter_q(database, view.filters, schema=schema)
    order = build_order_by(database, view.sorts, schema=schema)
    return list(database.rows.filter(q).order_by(*order))


def group_rows(view, rows: list) -> list[dict]:
    """ボードビュー用に ``group_by`` プロパティで行をグループ化する。

    返り値: ``[{"value": <グループ値 or None>, "rows": [DatabaseRow, ...]}, ...]``
    - select は config の options 順に空グループも並べる(空のレーンも出す)
    - multi_select は 1 行が複数グループに属しうる
    - 未設定(None / 空)は ``value=None`` のグループへ
    """
    database = view.database
    key = view.group_by
    schema = database.schema_map()
    if not key or key not in schema:
        raise ValueError("group_by に有効なプロパティを指定してください")
    prop = schema[key]

    groups: dict = {}
    order: list = []

    def ensure(value) -> None:
        if value not in groups:
            groups[value] = []
            order.append(value)

    if prop.type == "select":
        for name in _option_names(prop.config):
            ensure(name)
    ensure(None)  # 未設定レーン

    for row in rows:
        value = row.values.get(key)
        if isinstance(value, list):  # multi_select
            if not value:
                groups[None].append(row)
            for member in value:
                ensure(member)
                groups[member].append(row)
        else:
            bucket = value if value not in ("", None) else None
            ensure(bucket)
            groups[bucket].append(row)

    return [{"value": value, "rows": groups[value]} for value in order]
