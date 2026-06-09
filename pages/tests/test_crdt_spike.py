"""Phase 4-A スパイク: 文字粒度 CRDT(pycrdt)の収束性を固定する。

ここで証明するのは 4-D 本実装の前提となる CRDT の核心性質:
- 並行編集が同一状態へ収束する(競合が構造的に起きない)
- マージが可換・冪等(到着順・重複に強い → WS の再送/順序入れ替えに耐える)
- 新規 peer は state vector 交換で正しく同期できる
- CRDT → text の投影が ``Block.text`` への書き戻しに使える

Django に依存しない純粋な単体テスト(高速)。
"""
import pytest

from pages.crdt import BlockDoc

pytestmark = pytest.mark.unit


def _sync_new_peer(authority: BlockDoc) -> BlockDoc:
    """権威ドキュメントから新規 peer を同期する(独立初期化はしない)。"""
    peer = BlockDoc()
    peer.apply_update(authority.update_since(peer.state()))
    return peer


def test_initial_sync_projects_text():
    server = BlockDoc("hello")
    peer = _sync_new_peer(server)
    assert peer.text == "hello"


def test_concurrent_edits_converge():
    """両 peer が同時に別位置を編集 → 更新交換で同一状態へ収束する。"""
    a = BlockDoc("hello")
    b = _sync_new_peer(a)

    sv_a, sv_b = a.state(), b.state()
    a.insert(5, " world")  # 末尾に追記
    b.insert(0, "SAY: ")   # 先頭に追記

    delta_a = a.update_since(sv_a)
    delta_b = b.update_since(sv_b)
    a.apply_update(delta_b)
    b.apply_update(delta_a)

    assert a.text == b.text == "SAY: hello world"


def test_merge_is_idempotent():
    """同じ更新を二度適用しても壊れない(WS 再送に耐える)。"""
    a = BlockDoc("abc")
    b = _sync_new_peer(a)

    sv = b.state()
    a.insert(3, "def")
    delta = a.update_since(sv)

    b.apply_update(delta)
    b.apply_update(delta)  # 重複適用
    assert b.text == "abcdef"


def test_merge_is_order_independent():
    """3 つの並行更新を異なる順序で適用しても結果が一致する(可換性)。"""
    base = BlockDoc("X")
    p1 = _sync_new_peer(base)
    p2 = _sync_new_peer(base)
    p3 = _sync_new_peer(base)

    sv = base.state()
    p1.insert(1, "1")
    p2.insert(1, "2")
    p3.insert(1, "3")
    d1 = p1.update_since(sv)
    d2 = p2.update_since(sv)
    d3 = p3.update_since(sv)

    left = _sync_new_peer(base)
    right = _sync_new_peer(base)
    for d in (d1, d2, d3):
        left.apply_update(d)
    for d in (d3, d1, d2):  # 逆順・入れ替え
        right.apply_update(d)

    assert left.text == right.text


def test_from_update_restores_full_state():
    """``from_update`` で権威ドキュメントの全更新から peer を復元できる。"""
    server = BlockDoc("portfolio")
    peer = BlockDoc.from_update(server.update_since())  # 全更新(state=None)
    assert peer.text == "portfolio"


def test_delete_replicates():
    """削除も他 peer へ複製される。"""
    a = BlockDoc("hello world")
    b = _sync_new_peer(a)

    sv = b.state()
    a.delete(5, 6)  # " world" を削除
    b.apply_update(a.update_since(sv))
    assert a.text == b.text == "hello"


def test_delete_races_with_concurrent_insert():
    """削除と、削除範囲内への並行挿入が衝突しても両 peer は収束する。

    CRDT の難所(削除済み位置への挿入)。Yjs の tombstone により、
    挿入文字は残りつつ削除も適用され、両 peer が同一状態へ収束する。
    """
    a = BlockDoc("hello world")
    b = _sync_new_peer(a)

    sv_a, sv_b = a.state(), b.state()
    a.delete(5, 6)        # " world" を削除
    b.insert(8, "XYZ")    # 削除範囲 (" world") の内側へ挿入
    a.apply_update(b.update_since(sv_b))
    b.apply_update(a.update_since(sv_a))

    assert a.text == b.text  # 収束(具体値ではなく一致を固定)


def test_apply_update_rejects_non_bytes():
    doc = BlockDoc()
    with pytest.raises(TypeError):
        doc.apply_update("not bytes")  # type: ignore[arg-type]


def test_apply_update_rejects_oversized_payload():
    from pages.crdt import MAX_UPDATE_BYTES

    doc = BlockDoc()
    with pytest.raises(ValueError, match="too large"):
        doc.apply_update(b"\x00" * (MAX_UPDATE_BYTES + 1))


def test_apply_update_normalizes_invalid_payload():
    doc = BlockDoc()
    with pytest.raises(ValueError, match="invalid CRDT update payload"):
        doc.apply_update(b"\xff\xff\xff not a valid yjs update")


def test_independent_seeding_diverges_documents_gotcha():
    """独立初期化した peer はデルタをマージできない(同期プロトコルの根拠)。

    新規 peer を ``BlockDoc("abc")`` と独立に作ると内部 item id が分岐し、
    権威ドキュメントのデルタを当てても収束しない。必ず空 peer を
    state vector 交換で同期させること。本テストはその落とし穴を固定する。
    """
    a = BlockDoc("abc")
    rogue = BlockDoc("abc")  # 独立初期化(アンチパターン)

    sv = rogue.state()
    a.insert(3, "def")
    rogue.apply_update(a.update_since(sv))

    # 収束しない。実際の発散値を固定し、pycrdt のマージ挙動が両方向に
    # 変わったら検知できるようにする(負の表明だけだと偽合格を見逃す)。
    assert rogue.text == "abcdefabc"
    assert rogue.text != a.text
