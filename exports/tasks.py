"""エクスポート生成タスク(RQ ワーカーから呼ばれる関数 = import パスで指定可能)。"""
from .markdown import tree_to_markdown
from .models import Export


def run_export(export_id) -> None:
    """エクスポートを生成し、状態と内容を保存する。

    例外は握りつぶして ``failed`` + エラーメッセージへ落とす(ワーカーが落ちないように)。
    RQ から呼ばれても、開発/テストで同期実行されても同じ関数で動く。
    """
    # ワーカープロセスから import パスで呼ばれるため、ここで遅延 import する。
    from pages.serializers import serialize_block_tree

    export = Export.objects.select_related("page").filter(pk=export_id).first()
    if export is None:
        return

    export.status = Export.Status.RUNNING
    export.save(update_fields=["status", "updated_at"])

    try:
        page = export.page
        tree = serialize_block_tree(page.blocks.order_by("position"))
        if export.format == Export.Format.MARKDOWN:
            export.content = tree_to_markdown(tree, title=page.title)
        else:
            raise ValueError(f"未対応のエクスポート形式です: {export.format}")
        export.status = Export.Status.DONE
        export.error = ""
    except Exception as exc:  # ワーカーを落とさず失敗として記録する
        export.status = Export.Status.FAILED
        export.error = str(exc)

    export.save(update_fields=["content", "status", "error", "updated_at"])
