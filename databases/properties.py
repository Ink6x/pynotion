"""データベースプロパティの型と値バリデーション(スキーマレスの中核)。

値は JSONB(`DatabaseRow.values`)へ型なしで保持するため、型ごとの検証・正規化を
ここに集約する。ユーザー入力は信頼境界として扱い、各バリデータは**正規化済みの
新しい値**を返す(入力を破壊変更しない)。不正な値は ``ValueError`` を投げる。

Django 非依存の純ドメイン層にして単体テストで型ごとの境界を固定する。
"""
from __future__ import annotations

import math
import uuid
from collections.abc import Callable
from datetime import date, datetime
from enum import StrEnum


class PropertyType(StrEnum):
    """プロパティの型(Notion のプロパティ型に準拠)。"""

    TEXT = "text"
    NUMBER = "number"
    SELECT = "select"
    MULTI_SELECT = "multi_select"
    DATE = "date"
    CHECKBOX = "checkbox"
    RELATION = "relation"


# config から選択肢名の集合を取り出す。要素は "名前" 文字列か {"name": ...} を許容。
def _option_names(config: dict) -> list[str]:
    names: list[str] = []
    for opt in (config or {}).get("options", []):
        if isinstance(opt, str):
            names.append(opt)
        elif isinstance(opt, dict) and isinstance(opt.get("name"), str):
            names.append(opt["name"])
        else:
            raise ValueError("select の options は文字列か {name} で指定してください")
    return names


# 1 セルのテキスト上限。巨大文字列によるストレージ肥大・配信負荷を境界で防ぐ。
TEXT_MAX_LEN = 100_000


def _validate_text(value, config: dict) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("text は文字列で指定してください")
    if len(value) > TEXT_MAX_LEN:
        raise ValueError(f"text は {TEXT_MAX_LEN} 文字以内で指定してください")
    return value


def _validate_number(value, config: dict) -> float | int | None:
    if value is None:
        return None
    # bool は int のサブクラスだが数値プロパティとしては受け付けない
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("number は数値で指定してください")
    if not math.isfinite(value):
        raise ValueError("number に NaN / Infinity は使えません")
    return value


def _validate_select(value, config: dict):
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("select は文字列で指定してください")
    if value not in _option_names(config):
        raise ValueError(f"select の選択肢にない値です: {value!r}")
    return value


def _validate_multi_select(value, config: dict) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("multi_select は配列で指定してください")
    allowed = _option_names(config)
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("multi_select の要素は文字列で指定してください")
        if item not in allowed:
            raise ValueError(f"multi_select の選択肢にない値です: {item!r}")
        if item not in result:  # 重複は畳む(順序は保持)
            result.append(item)
    return result


def _validate_date(value, config: dict) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("date は ISO 8601 文字列で指定してください")
    try:
        # 日付 / 日時の両方を許容し、ISO 文字列へ正規化する
        if len(value) <= 10:
            return date.fromisoformat(value).isoformat()
        return datetime.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError(f"date が ISO 8601 として不正です: {value!r}") from exc


def _validate_checkbox(value, config: dict) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise ValueError("checkbox は真偽値で指定してください")
    return value


def _validate_relation(value, config: dict) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("relation は配列で指定してください")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("relation の要素は行 id(UUID 文字列)で指定してください")
        try:
            normalized = str(uuid.UUID(item))
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValueError(f"relation の行 id が UUID として不正です: {item!r}") from exc
        if normalized not in result:
            result.append(normalized)
    return result


_VALIDATORS: dict[PropertyType, Callable[[object, dict], object]] = {
    PropertyType.TEXT: _validate_text,
    PropertyType.NUMBER: _validate_number,
    PropertyType.SELECT: _validate_select,
    PropertyType.MULTI_SELECT: _validate_multi_select,
    PropertyType.DATE: _validate_date,
    PropertyType.CHECKBOX: _validate_checkbox,
    PropertyType.RELATION: _validate_relation,
}


def empty_value(ptype: str | PropertyType):
    """その型の「未入力」を表す正規値(行作成時の既定)。"""
    return _VALIDATORS[PropertyType(ptype)](None, {})


def validate_value(ptype: str | PropertyType, value, config: dict | None = None):
    """型 ``ptype`` に対し ``value`` を検証し、正規化済みの新しい値を返す。

    不正な型・選択肢外・パース不能は ``ValueError``。
    """
    try:
        validator = _VALIDATORS[PropertyType(ptype)]
    except (KeyError, ValueError) as exc:
        raise ValueError(f"未知のプロパティ型です: {ptype!r}") from exc
    return validator(value, config or {})


def _candidate(new_type: PropertyType, value):
    """旧値を新しい型に寄せた「候補値」を作る(検証は呼び出し側で行う)。"""
    if new_type == PropertyType.TEXT:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, list):
            return ", ".join(str(x) for x in value)
        return str(value)
    if new_type == PropertyType.NUMBER:
        if isinstance(value, bool):
            return None
        if isinstance(value, int | float):
            return value
        if isinstance(value, str):
            try:
                num = float(value)
            except ValueError:
                return None
            return int(num) if num.is_integer() else num
        return None
    if new_type == PropertyType.SELECT:
        if isinstance(value, list):
            return value[0] if value else None
        if value is None:
            return None
        return str(value)
    if new_type == PropertyType.MULTI_SELECT:
        if isinstance(value, list):
            return [str(x) for x in value]
        if value in (None, ""):
            return []
        return [str(value)]
    if new_type == PropertyType.DATE:
        return value if isinstance(value, str) else None
    if new_type == PropertyType.CHECKBOX:
        if isinstance(value, bool):
            return value
        if isinstance(value, int | float):
            return bool(value)  # 0 / 0.0 → False、非ゼロ → True
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes", "on")
        return False
    # RELATION(到達する最後の型)
    return [str(x) for x in value] if isinstance(value, list) else []


def coerce_value(new_type: str | PropertyType, value, config: dict | None = None):
    """型変更時に旧値を新しい型へ移行する。

    旧値から候補を作り、新しい型で検証する。移行できない値は新しい型の空値へ
    落とす(型変更でデータが壊れて保存されないよう、必ず正規値を返す)。
    """
    new_type = PropertyType(new_type)
    candidate = _candidate(new_type, value)
    try:
        return validate_value(new_type, candidate, config or {})
    except ValueError:
        return empty_value(new_type)
