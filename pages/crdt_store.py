"""ブロックテキストの CRDT ライブ状態と永続化(Phase 4-D)。

設計(`docs/plan/02-architecture.md` の判断記録 #7、4-A スパイク):

- **ライブなマージ状態は Django cache** に持つ(`crdt:block:<id>`)。dev/テストは
  LocMemCache、本番は Redis(プレゼンスと同じ層)。最初のアクセス時に
  ``Block.text`` から種を作る(**サーバが唯一の種まき手**。クライアントは空ドキュメントで
  繋いで state vector 交換で同期する = 独立初期化の発散を避ける)。
- **耐久的な source of truth は ``Block.text`` 行**。ライブ状態を一定間隔で投影して
  書き戻す(``maybe_flush``)。テキストだけ CRDT 化し、構造操作(作成/移動/削除)は
  従来どおり REST + 楽観ロックのまま。
- cache の read-modify-write はプレゼンスと同じく多ワーカーで競合しうるが、各更新は
  全クライアントへブロードキャストされ各自のローカル doc が収束するため、サーバ
  cache の取りこぼしは「新規参加者の初期同期がわずかに古い」程度に留まる割り切り。
"""
import base64
import binascii
import time

from django.core.cache import cache
from django.db.models import F
from django.utils import timezone

from .crdt import BlockDoc
from .models import Block


def _decode(b64: str | None) -> bytes | None:
    """base64 をデコードする。不正なら None(信頼境界。例外で接続を落とさない)。"""
    if not b64:
        return None
    try:
        return base64.b64decode(b64)
    except (binascii.Error, ValueError):
        return None

CRDT_TTL = 3600
# ``Block.text`` への書き戻し最小間隔(秒)。キーストロークごとの DB 書き込みを抑える。
FLUSH_INTERVAL_SECONDS = 2


def _state_key(block_id) -> str:
    return f"crdt:block:{block_id}"


def _flush_key(block_id) -> str:
    return f"crdt:flush:{block_id}"


def _load_doc(block_id, seed_text: str) -> BlockDoc:
    """cache のライブ状態を読み込む。無ければ ``seed_text`` から種を作って保存する。

    cold cache で同時アクセスすると両者が独立に種を作り片方の cache.set が勝つ
    (= 一方の更新を cache が取りこぼす)競合がある。各更新は全クライアントへ
    ブロードキャストされ各自のローカル doc が収束するため影響は限定的という割り切り
    (プレゼンスの RMW と同じ。本番 Redis なら SETNX 相当で塞げる)。
    """
    state = cache.get(_state_key(block_id))
    if state is None:
        doc = BlockDoc(seed_text)
        cache.set(_state_key(block_id), doc.update_since(), CRDT_TTL)
        return doc
    return BlockDoc.from_update(state)


def sync_update(block_id, seed_text: str, client_state_b64: str | None) -> str:
    """クライアントの state vector に対し不足分の更新(base64)を返す。

    クライアントは空ドキュメント + 自身の state vector を送る。サーバはライブ状態
    (無ければ ``seed_text`` で種まき)との差分を返し、クライアントはそれを適用して
    サーバと同じ item id を持つテキストへ同期する。
    """
    doc = _load_doc(block_id, seed_text)
    return base64.b64encode(doc.update_since(_decode(client_state_b64))).decode()


def apply_update(block_id, seed_text: str, update_b64: str) -> str:
    """クライアントの更新(base64)をライブ状態へマージし、投影テキストを返す。"""
    doc = _load_doc(block_id, seed_text)
    update = _decode(update_b64)
    if update is None:  # 不正な base64 は捨てる(現在テキストを返す)
        return doc.text
    doc.apply_update(update)
    cache.set(_state_key(block_id), doc.update_since(), CRDT_TTL)
    return doc.text


def project_text(block_id) -> str | None:
    """ライブ状態の現在テキスト(無ければ None)。"""
    state = cache.get(_state_key(block_id))
    return BlockDoc.from_update(state).text if state is not None else None


def flush(block_id) -> bool:
    """ライブ状態のテキストを ``Block.text`` へ書き戻す(変化があれば version も +1)。

    書き戻したら True。version は ``F("version") + 1`` の**アトミック更新**にし、
    同時 flush(maybe_flush と切断時 flush が別ワーカーで重なる等)で version 更新を
    取りこぼさない。``exclude(text=...)`` でテキスト未変化なら書き込まない。
    ``.update()`` は auto_now を発火しないため ``updated_at`` を明示する。
    """
    text = project_text(block_id)
    if text is None:
        return False
    updated = (
        Block.objects.filter(pk=block_id)
        .exclude(text=text)
        .update(text=text, version=F("version") + 1, updated_at=timezone.now())
    )
    return updated > 0


def maybe_flush(block_id, *, now: float | None = None) -> bool:
    """直近の書き戻しから ``FLUSH_INTERVAL_SECONDS`` 以上経っていれば書き戻す。

    スロットルのタイムスタンプは**実際に書き込んだときだけ**更新する(no-op で
    ウィンドウを消費して以降の本当の変更を遅らせないため)。
    """
    now = time.time() if now is None else now
    last = cache.get(_flush_key(block_id))
    if last is not None and now - last < FLUSH_INTERVAL_SECONDS:
        return False
    if flush(block_id):
        cache.set(_flush_key(block_id), now, CRDT_TTL)
        return True
    return False
