"""fractional indexing — 並び順を表す文字列キーの生成。

辞書順で比較できる文字列キーで並び順を表現する。任意の隣接する
2 キーの間に必ず新しいキーを生成できるため、ブロックやページの
並べ替え時に他の行を更新する必要がない。

アルゴリズムは rocicorp/fractional-indexing の midpoint 方式を移植。
キーは ALPHABET の文字のみで構成され、末尾が '0' になることはない
(末尾 '0' のキーはその直前にキーを挿入できなくなるため)。
"""

ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"
_BASE = len(ALPHABET)


def key_between(prev: str | None, next_: str | None) -> str:
    """prev < key < next_ となるキーを返す。

    prev=None は下限なし(先頭挿入)、next_=None は上限なし(末尾追加)。
    """
    if prev is not None:
        _validate(prev, "prev")
    if next_ is not None:
        _validate(next_, "next")
    if prev is not None and next_ is not None and prev >= next_:
        raise ValueError(f"prev は next より小さい必要があります: {prev!r} >= {next_!r}")
    return _midpoint(prev or "", next_)


def _validate(key: str, name: str) -> None:
    if not key:
        raise ValueError(f"{name} は空文字列にできません")
    if any(ch not in ALPHABET for ch in key):
        raise ValueError(f"{name} に不正な文字が含まれています: {key!r}")
    if key.endswith(ALPHABET[0]):
        raise ValueError(f"{name} は '0' で終われません: {key!r}")


def _midpoint(a: str, b: str | None) -> str:
    """a < 結果 < b となる文字列を返す。a は '' 可、b=None は上限なし。"""
    if b is not None:
        # 共通プレフィックスを取り除いて残りを再帰処理
        n = 0
        while n < len(b) and (a[n] if n < len(a) else ALPHABET[0]) == b[n]:
            n += 1
        if n > 0:
            return b[:n] + _midpoint(a[n:], b[n:])
    # 先頭の桁が異なる
    digit_a = ALPHABET.index(a[0]) if a else 0
    digit_b = ALPHABET.index(b[0]) if b is not None else _BASE
    if digit_b - digit_a > 1:
        return ALPHABET[(digit_a + digit_b) // 2]
    # 桁が隣接している場合
    if b is not None and len(b) > 1:
        return b[:1]
    return ALPHABET[digit_a] + _midpoint(a[1:], None)
