"""宣言的フィルタ / ソート JSON を Django ORM の Q / order_by へ安全に変換する。

設計(`docs/plan/02-architecture.md` D 節、判断記録 #4):

スキーマレスな行(``DatabaseRow.values`` JSONB)に対する検索条件を、ユーザーが
保存した **宣言的 JSON** から組み立てる。これは「動的クエリ」であり SQL
インジェクションの温床になりやすいため、次の三重の防御で安全性を担保する:

1. **演算子はホワイトリスト**(``_OPERATORS`` にある op しか通さない)
2. **フィールドはスキーマ照合**(``database`` に実在する property key のみ。
   key 自体も `^[A-Za-z0-9_]+$` 相当に制限済み = `values__<key>` への注入不可)
3. **値は ORM 経由のみ**でクエリへ渡す(生 SQL を一切組み立てない。
   値は常にパラメータ化される)

入力はすべて信頼境界。不正な構造・未知の演算子・未知のプロパティ・非スカラ値は
``ValueError`` を投げる(API 層で 400 に変換)。
"""
from __future__ import annotations

from collections.abc import Callable

from django.db.models import Q

# フィルタの 1 つの葉が取りうる演算子 → (lookup サフィックス, 否定するか)。
# ここに無い演算子は一切受け付けない(ホワイトリスト)。
_OPERATORS: dict[str, Callable[[str, object], Q]] = {}


def _op(name: str):
    def register(fn: Callable[[str, object], Q]) -> Callable[[str, object], Q]:
        _OPERATORS[name] = fn
        return fn

    return register


def _field(key: str) -> str:
    return f"values__{key}"


@_op("eq")
def _eq(key, value) -> Q:
    return Q(**{_field(key): value})


@_op("neq")
def _neq(key, value) -> Q:
    return ~Q(**{_field(key): value})


@_op("contains")
def _contains(key, value) -> Q:
    return Q(**{f"{_field(key)}__icontains": value})


@_op("not_contains")
def _not_contains(key, value) -> Q:
    return ~Q(**{f"{_field(key)}__icontains": value})


@_op("gt")
def _gt(key, value) -> Q:
    return Q(**{f"{_field(key)}__gt": value})


@_op("gte")
def _gte(key, value) -> Q:
    return Q(**{f"{_field(key)}__gte": value})


@_op("lt")
def _lt(key, value) -> Q:
    return Q(**{f"{_field(key)}__lt": value})


@_op("lte")
def _lte(key, value) -> Q:
    return Q(**{f"{_field(key)}__lte": value})


@_op("in")
def _in(key, value) -> Q:
    if not isinstance(value, list):
        raise ValueError("in 演算子の値は配列で指定してください")
    return Q(**{f"{_field(key)}__in": value})


# 空 = None / "" / [](型ごとの空値)。3 つを OR で拾う。
def _is_empty_q(key: str) -> Q:
    field = _field(key)
    return Q(**{field: None}) | Q(**{field: ""}) | Q(**{field: []})


@_op("is_empty")
def _is_empty(key, value) -> Q:
    return _is_empty_q(key)


@_op("is_not_empty")
def _is_not_empty(key, value) -> Q:
    return ~_is_empty_q(key)


# 値として許すスカラ(と in 用の list)。dict や任意オブジェクトは弾く。
_SCALAR = (str, int, float, bool, type(None))


def _validate_leaf_value(op: str, value) -> None:
    if op in ("is_empty", "is_not_empty"):
        return
    if op == "in":
        return  # _in が中身を検証する
    if not isinstance(value, _SCALAR):
        raise ValueError(f"フィルタ値はスカラで指定してください: {value!r}")


def build_filter_q(database, spec) -> Q:
    """フィルタ JSON を Q へ変換する(再帰)。

    受け付ける形:
    - ``{}`` / ``None`` → すべて一致(``Q()``)
    - ``{"and": [spec, ...]}`` / ``{"or": [spec, ...]}`` / ``{"not": spec}``
    - 葉 ``{"property": key, "op": name, "value": v}``
    """
    if not spec:
        return Q()
    if not isinstance(spec, dict):
        raise ValueError("フィルタは object で指定してください")

    if "and" in spec or "or" in spec:
        if len(spec) != 1:
            raise ValueError("and / or は単独のキーで指定してください")
        connector = "and" if "and" in spec else "or"
        children = spec[connector]
        if not isinstance(children, list) or not children:
            raise ValueError(f"{connector} は非空の配列で指定してください")
        combined: Q | None = None
        for child in children:
            q = build_filter_q(database, child)
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
        return ~build_filter_q(database, spec["not"])

    # 葉
    return _build_leaf(database, spec)


def _build_leaf(database, spec: dict) -> Q:
    prop = spec.get("property")
    op = spec.get("op")
    value = spec.get("value")

    schema = database.schema_map()
    if prop not in schema:
        # 未定義プロパティでの絞り込みは拒否(存在しない列名の注入を防ぐ)
        raise ValueError(f"未知のプロパティです: {prop!r}")
    if op not in _OPERATORS:
        raise ValueError(f"許可されていない演算子です: {op!r}")
    _validate_leaf_value(op, value)
    return _OPERATORS[op](schema[prop].key, value)


def build_order_by(database, sorts) -> list[str]:
    """ソート JSON を ``order_by`` 引数列へ変換する。

    ``[{"property": key, "direction": "asc"|"desc"}, ...]``。
    末尾に安定ソート用の ``position`` を必ず付ける。
    """
    if not sorts:
        return ["position"]
    if not isinstance(sorts, list):
        raise ValueError("sorts は配列で指定してください")
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


def rows_for_view(view) -> list:
    """ビューの filters / sorts を適用した ``DatabaseRow`` のリストを返す。"""
    database = view.database
    q = build_filter_q(database, view.filters)
    order = build_order_by(database, view.sorts)
    return list(database.rows.filter(q).order_by(*order))
