"""プロパティ型バリデーションの単体テスト(Django 非依存)。"""
import pytest

from databases.properties import PropertyType, empty_value, validate_value

pytestmark = pytest.mark.unit

SELECT_CONFIG = {"options": ["Todo", "Doing", "Done"]}
SELECT_CONFIG_DICTS = {"options": [{"name": "Low"}, {"name": "High"}]}


# --- text -------------------------------------------------------------------


def test_text_passthrough():
    assert validate_value("text", "hello") == "hello"


def test_text_none_becomes_empty():
    assert validate_value("text", None) == ""


def test_text_rejects_non_string():
    with pytest.raises(ValueError, match="text"):
        validate_value("text", 123)


# --- number -----------------------------------------------------------------


@pytest.mark.parametrize("value", [0, 42, -3, 3.14])
def test_number_accepts_numeric(value):
    assert validate_value("number", value) == value


def test_number_none_stays_none():
    assert validate_value("number", None) is None


def test_number_rejects_bool():
    # bool は int サブクラスだが number としては拒否する
    with pytest.raises(ValueError):
        validate_value("number", True)


def test_number_rejects_string():
    with pytest.raises(ValueError):
        validate_value("number", "42")


def test_number_rejects_infinity():
    with pytest.raises(ValueError, match="Infinity"):
        validate_value("number", float("inf"))


# --- select -----------------------------------------------------------------


def test_select_accepts_option():
    assert validate_value("select", "Doing", SELECT_CONFIG) == "Doing"


def test_select_accepts_dict_options():
    assert validate_value("select", "High", SELECT_CONFIG_DICTS) == "High"


def test_select_empty_becomes_none():
    assert validate_value("select", "", SELECT_CONFIG) is None
    assert validate_value("select", None, SELECT_CONFIG) is None


def test_select_rejects_unknown_option():
    with pytest.raises(ValueError, match="選択肢"):
        validate_value("select", "Nope", SELECT_CONFIG)


def test_select_rejects_non_string():
    with pytest.raises(ValueError, match="文字列"):
        validate_value("select", 5, SELECT_CONFIG)


def test_select_rejects_malformed_options_config():
    with pytest.raises(ValueError, match="options"):
        validate_value("select", "x", {"options": [123]})


# --- multi_select -----------------------------------------------------------


def test_multi_select_accepts_subset():
    assert validate_value("multi_select", ["Todo", "Done"], SELECT_CONFIG) == ["Todo", "Done"]


def test_multi_select_none_becomes_empty_list():
    assert validate_value("multi_select", None, SELECT_CONFIG) == []


def test_multi_select_dedupes_preserving_order():
    assert validate_value("multi_select", ["Done", "Todo", "Done"], SELECT_CONFIG) == [
        "Done",
        "Todo",
    ]


def test_multi_select_rejects_non_list():
    with pytest.raises(ValueError, match="配列"):
        validate_value("multi_select", "Todo", SELECT_CONFIG)


def test_multi_select_rejects_unknown_member():
    with pytest.raises(ValueError, match="選択肢"):
        validate_value("multi_select", ["Todo", "Nope"], SELECT_CONFIG)


def test_multi_select_rejects_non_string_member():
    with pytest.raises(ValueError, match="要素は文字列"):
        validate_value("multi_select", ["Todo", 7], SELECT_CONFIG)


# --- date -------------------------------------------------------------------


def test_date_accepts_iso_date():
    assert validate_value("date", "2026-06-09") == "2026-06-09"


def test_date_accepts_iso_datetime():
    assert validate_value("date", "2026-06-09T10:30:00") == "2026-06-09T10:30:00"


def test_date_empty_becomes_none():
    assert validate_value("date", "") is None
    assert validate_value("date", None) is None


def test_date_rejects_garbage():
    with pytest.raises(ValueError, match="ISO 8601"):
        validate_value("date", "yesterday")


def test_date_rejects_non_string():
    with pytest.raises(ValueError, match="ISO 8601"):
        validate_value("date", 20260609)


# --- checkbox ---------------------------------------------------------------


def test_checkbox_accepts_bool():
    assert validate_value("checkbox", True) is True
    assert validate_value("checkbox", False) is False


def test_checkbox_none_becomes_false():
    assert validate_value("checkbox", None) is False


def test_checkbox_rejects_non_bool():
    with pytest.raises(ValueError, match="真偽値"):
        validate_value("checkbox", "true")


# --- relation ---------------------------------------------------------------


def test_relation_normalizes_uuids():
    raw = ["12345678-1234-5678-1234-567812345678"]
    assert validate_value("relation", raw) == raw


def test_relation_none_becomes_empty_list():
    assert validate_value("relation", None) == []


def test_relation_dedupes():
    u = "12345678-1234-5678-1234-567812345678"
    assert validate_value("relation", [u, u]) == [u]


def test_relation_rejects_non_uuid():
    with pytest.raises(ValueError, match="UUID"):
        validate_value("relation", ["not-a-uuid"])


def test_relation_rejects_non_list():
    with pytest.raises(ValueError, match="配列"):
        validate_value("relation", "12345678-1234-5678-1234-567812345678")


def test_relation_rejects_non_string_member():
    with pytest.raises(ValueError, match="行 id"):
        validate_value("relation", [123])


# --- dispatch ---------------------------------------------------------------


def test_unknown_type_raises():
    with pytest.raises(ValueError, match="未知のプロパティ型"):
        validate_value("rating", 5)


@pytest.mark.parametrize("ptype", list(PropertyType))
def test_empty_value_is_valid_for_every_type(ptype):
    # 空値は同じ型の検証を必ず通る(行作成時の既定として安全)
    empty = empty_value(ptype)
    assert validate_value(ptype, empty, SELECT_CONFIG) == empty
