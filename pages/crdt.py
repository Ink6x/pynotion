"""ブロックテキストの CRDT(文字粒度の競合解決)— Phase 4-A スパイク検証済みの基盤。

設計判断(`docs/plan/02-architecture.md` の判断記録 #6 / #7 参照):

- **自前 OT は書かない**。Yjs(クライアント)互換の CRDT を採用し、サーバ側
  バインディングは **pycrdt** を選ぶ。y-py は 2023 年で更新停止しているため、
  後継で保守が続く pycrdt(Jupyter コラボレーション基盤で実績)を選定した。
- **権威ドキュメントの更新ストリームから同期する**。新規 peer を独立に
  ``Text(text)`` で初期化すると内部 item id が分岐し、以降のデルタがマージ
  できなくなる(スパイクで確認)。必ず空ドキュメントを state vector 交換で
  同期させる(Yjs の標準同期プロトコル)。
- **永続化との関係**: ライブな ``BlockDoc`` が編集中のマージ権威、``Block.text``
  行が耐久的な source of truth。デバウンスして CRDT → text を投影し
  ``Block.text`` へ書き戻す(4-D で実装)。

このモジュールは Django に依存しない純ドメイン層に保ち、単体テストで収束性を
固定する。Channels Consumer / 永続化との結線は 4-D で行う。
"""
from __future__ import annotations

from pycrdt import Doc, Text

# ブロック本文を保持する root 型のキー。クライアント(Yjs)側と一致させる。
TEXT_KEY = "text"


class BlockDoc:
    """1 ブロックのテキストを表す CRDT ドキュメント。

    Yjs バイナリ更新プロトコル互換。``state()`` / ``update_since()`` /
    ``apply_update()`` で peer 間の差分同期を行い、``text`` で現在値を投影する。
    """

    def __init__(self, text: str = "") -> None:
        self._doc = Doc()
        self._text = Text()
        # root 型を登録してから種を入れる(登録前は読み書きできない)。
        self._doc[TEXT_KEY] = self._text
        if text:
            self._text.insert(0, text)

    @classmethod
    def from_update(cls, update: bytes) -> BlockDoc:
        """権威ドキュメントの全更新から peer を復元する(独立初期化はしない)。"""
        doc = cls()
        doc.apply_update(update)
        return doc

    @property
    def text(self) -> str:
        """現在のテキストを投影する(``Block.text`` への書き戻しに使う)。"""
        return str(self._text)

    def apply_update(self, update: bytes) -> None:
        """他 peer からのバイナリ更新をマージする(可換・冪等)。"""
        self._doc.apply_update(update)

    def state(self) -> bytes:
        """自身の state vector(どこまで観測済みか)。差分要求の起点に使う。"""
        return self._doc.get_state()

    def update_since(self, state: bytes | None = None) -> bytes:
        """``state`` 以降の差分更新を符号化する。

        ``state`` が None なら全更新(新規 peer の初期同期用)。
        """
        if state is None:
            return self._doc.get_update()
        return self._doc.get_update(state)

    # --- ローカル編集(テスト・将来のサーバ側補正用)------------------------

    def insert(self, index: int, value: str) -> None:
        self._text.insert(index, value)

    def delete(self, index: int, length: int) -> None:
        del self._text[index : index + length]
