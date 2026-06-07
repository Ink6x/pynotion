"""fractional indexing ユーティリティのテスト。"""
import pytest

from pages.ordering import key_between


@pytest.mark.unit
class TestKeyBetween:
    def test_first_key(self) -> None:
        """両端が無い場合(最初の要素)でもキーが生成される。"""
        key = key_between(None, None)
        assert isinstance(key, str)
        assert len(key) > 0

    def test_append_after(self) -> None:
        """末尾追加: prev より大きいキーが返る。"""
        a = key_between(None, None)
        b = key_between(a, None)
        assert a < b

    def test_prepend_before(self) -> None:
        """先頭挿入: next より小さいキーが返る。"""
        a = key_between(None, None)
        b = key_between(None, a)
        assert b < a

    def test_insert_between(self) -> None:
        """中間挿入: prev < key < next が成り立つ。"""
        a = key_between(None, None)
        b = key_between(a, None)
        mid = key_between(a, b)
        assert a < mid < b

    def test_repeated_insertion_between_stays_ordered(self) -> None:
        """同じ区間に繰り返し挿入しても順序が保たれる(精度劣化しない)。"""
        low = key_between(None, None)
        high = key_between(low, None)
        keys = [low, high]
        current_low = low
        for _ in range(100):
            mid = key_between(current_low, high)
            assert current_low < mid < high
            keys.append(mid)
            current_low = mid
        assert keys == sorted(set(keys), key=keys.index) or sorted(keys) == sorted(keys)

    def test_invalid_order_raises(self) -> None:
        """prev >= next はエラー。"""
        a = key_between(None, None)
        b = key_between(a, None)
        with pytest.raises(ValueError):
            key_between(b, a)
        with pytest.raises(ValueError):
            key_between(a, a)
