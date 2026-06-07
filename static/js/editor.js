// pynotion — contenteditable ベースのブロックエディタ
// Enter で分割 / Backspace で結合 / Markdown 風ショートカット / 自動保存。
// 日本語 IME 変換中 (isComposing) のキーは奪わない。
const Editor = (() => {
  "use strict";

  const SAVE_DELAY_MS = 450;
  // 段落で入力すると自動変換される Markdown 風プレフィックス
  const AUTOFORMAT_RULES = [
    { pattern: /^#\s$/, type: "heading_1" },
    { pattern: /^##\s$/, type: "heading_2" },
    { pattern: /^###\s$/, type: "heading_3" },
    { pattern: /^[-*]\s$/, type: "bulleted_list_item" },
    { pattern: /^1[.．]\s$/, type: "numbered_list_item" },
    { pattern: /^\[\s?\]\s$/, type: "to_do" },
    { pattern: /^>\s$/, type: "quote" },
    { pattern: /^```$/, type: "code" },
    { pattern: /^---$/, type: "divider" },
  ];
  // Enter で同じタイプを引き継ぐブロック
  const INHERIT_TYPES = new Set(["to_do", "bulleted_list_item", "numbered_list_item"]);
  const TEXTLESS_TYPES = new Set(["divider"]);

  /** @type {object | null} */
  let page = null;
  /** @type {Array<object>} */
  let blocks = [];
  /** @type {Map<string, number>} ブロック ID →保存タイマー */
  const saveTimers = new Map();

  function root() {
    return document.getElementById("editor");
  }

  /* ----------------------------------------------------------------------
     公開 API
     ---------------------------------------------------------------------- */

  /** @param {object} p ページ @param {Array<object>} blockList */
  function open(p, blockList) {
    page = p;
    blocks = blockList.slice();
    render();
  }

  /** タイトルから Enter で呼ばれる。先頭ブロックへフォーカス。 */
  async function focusFirstBlock() {
    if (!page) return;
    if (blocks.length === 0) {
      await appendParagraph();
      return;
    }
    const first = blocks.find((b) => !TEXTLESS_TYPES.has(b.type));
    if (first) focusBlock(first.id, 0);
  }

  /* ----------------------------------------------------------------------
     描画
     ---------------------------------------------------------------------- */

  function render() {
    const el = root();
    el.innerHTML = "";
    blocks.forEach((block) => el.appendChild(renderBlock(block)));
  }

  /** @param {object} block @returns {HTMLElement} */
  function renderBlock(block) {
    const row = document.createElement("div");
    row.className = "block type-" + block.type;
    if (block.type === "to_do" && block.checked) row.classList.add("is-checked");
    row.dataset.blockId = block.id;

    const handle = document.createElement("div");
    handle.className = "block-handle";
    handle.textContent = "⠿";
    handle.title = "ドラッグして移動";
    handle.draggable = true;
    handle.addEventListener("dragstart", (e) => {
      dragState.id = block.id;
      row.classList.add("is-dragging");
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", block.id);
    });
    handle.addEventListener("dragend", () => {
      dragState.id = null;
      dragState.afterId = undefined;
      row.classList.remove("is-dragging");
      clearDropIndicator();
    });
    row.appendChild(handle);

    if (block.type === "divider") {
      const hr = document.createElement("hr");
      hr.className = "block-divider";
      row.appendChild(hr);
      return row;
    }

    if (block.type === "to_do") {
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.className = "block-checkbox";
      checkbox.checked = block.checked;
      checkbox.addEventListener("change", () => toggleChecked(block.id, checkbox.checked));
      row.appendChild(checkbox);
    }

    const content = document.createElement("div");
    content.className = "block-content";
    content.contentEditable = "true";
    content.spellcheck = false;
    content.textContent = block.text;
    content.dataset.placeholder = placeholderFor(block.type);
    content.addEventListener("input", () => handleInput(block.id));
    content.addEventListener("keydown", (e) => handleKeydown(e, block.id));
    row.appendChild(content);

    return row;
  }

  /** @param {string} type @returns {string} */
  function placeholderFor(type) {
    switch (type) {
      case "heading_1":
        return "見出し1";
      case "heading_2":
        return "見出し2";
      case "heading_3":
        return "見出し3";
      case "to_do":
        return "ToDo";
      case "quote":
        return "引用";
      case "code":
        return "コードを入力";
      default:
        return "入力して、コマンドは「/」を使用";
    }
  }

  /* ----------------------------------------------------------------------
     状態ヘルパー (blocks 配列は常に新しい配列/オブジェクトで置き換える)
     ---------------------------------------------------------------------- */

  /** @param {string} id */
  function blockIndex(id) {
    return blocks.findIndex((b) => b.id === id);
  }

  /** @param {string} id @param {object} patch */
  function patchBlock(id, patch) {
    blocks = blocks.map((b) => (b.id === id ? { ...b, ...patch } : b));
  }

  /** @param {string} id @returns {HTMLElement | null} */
  function contentEl(id) {
    const row = root().querySelector(`[data-block-id="${id}"]`);
    return row ? row.querySelector(".block-content") : null;
  }

  /** @param {string} id @param {number | "end"} offset */
  function focusBlock(id, offset) {
    const el = contentEl(id);
    if (!el) return;
    el.focus();
    setCaret(el, offset === "end" ? el.textContent.length : offset);
  }

  /* ----------------------------------------------------------------------
     キャレット操作
     ---------------------------------------------------------------------- */

  /** @param {HTMLElement} el @returns {number} 要素先頭からの文字オフセット */
  function caretOffset(el) {
    const sel = window.getSelection();
    if (!sel || sel.rangeCount === 0) return 0;
    const range = sel.getRangeAt(0).cloneRange();
    range.selectNodeContents(el);
    range.setEnd(sel.getRangeAt(0).endContainer, sel.getRangeAt(0).endOffset);
    return range.toString().length;
  }

  /** @param {HTMLElement} el @param {number} offset */
  function setCaret(el, offset) {
    const sel = window.getSelection();
    const range = document.createRange();
    let remaining = offset;
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let node = walker.nextNode();
    while (node) {
      if (remaining <= node.textContent.length) {
        range.setStart(node, remaining);
        range.collapse(true);
        sel.removeAllRanges();
        sel.addRange(range);
        return;
      }
      remaining -= node.textContent.length;
      node = walker.nextNode();
    }
    range.selectNodeContents(el);
    range.collapse(false);
    sel.removeAllRanges();
    sel.addRange(range);
  }

  /** @param {HTMLElement} el */
  function hasSelection() {
    const sel = window.getSelection();
    return sel && !sel.isCollapsed;
  }

  /* ----------------------------------------------------------------------
     入力・自動保存・自動フォーマット
     ---------------------------------------------------------------------- */

  /** @param {string} id */
  function handleInput(id) {
    const el = contentEl(id);
    if (!el) return;
    const block = blocks[blockIndex(id)];
    const text = el.textContent;

    if (window.SlashMenu) SlashMenu.onInput(id, el);

    if (block.type === "paragraph" && !(window.SlashMenu && SlashMenu.isOpen())) {
      const rule = AUTOFORMAT_RULES.find((r) => r.pattern.test(text));
      if (rule) {
        applyAutoformat(id, rule.type);
        return;
      }
    }

    patchBlock(id, { text });
    scheduleSave(id);
  }

  /** @param {string} id @param {string} newType */
  async function applyAutoformat(id, newType) {
    if (newType === "divider") {
      await convertToDivider(id);
      return;
    }
    patchBlock(id, { type: newType, text: "" });
    rerenderBlock(id);
    focusBlock(id, 0);
    await save(id, { type: newType, text: "" });
  }

  /** 段落を区切り線に変換し、直後に新しい段落を作る。 @param {string} id */
  async function convertToDivider(id) {
    patchBlock(id, { type: "divider", text: "" });
    rerenderBlock(id);
    await save(id, { type: "divider", text: "" });
    const block = blocks[blockIndex(id)];
    await insertBlockAfter(block, "paragraph", "");
  }

  /** @param {string} id */
  function rerenderBlock(id) {
    const row = root().querySelector(`[data-block-id="${id}"]`);
    if (!row) return;
    row.replaceWith(renderBlock(blocks[blockIndex(id)]));
  }

  /** @param {string} id */
  function scheduleSave(id) {
    if (saveTimers.has(id)) clearTimeout(saveTimers.get(id));
    saveTimers.set(
      id,
      setTimeout(() => {
        const block = blocks[blockIndex(id)];
        if (block) save(id, { text: block.text });
      }, SAVE_DELAY_MS)
    );
  }

  /** @param {string} id @param {object} payload */
  async function save(id, payload) {
    try {
      await API.updateBlock(id, payload);
    } catch (err) {
      App.toast("保存に失敗しました: " + err.message);
    }
  }

  /** @param {string} id @param {boolean} checked */
  async function toggleChecked(id, checked) {
    patchBlock(id, { checked });
    const row = root().querySelector(`[data-block-id="${id}"]`);
    if (row) row.classList.toggle("is-checked", checked);
    await save(id, { checked });
  }

  /* ----------------------------------------------------------------------
     キー操作 (Enter 分割 / Backspace 結合 / 矢印移動)
     ---------------------------------------------------------------------- */

  /** @param {KeyboardEvent} e @param {string} id */
  function handleKeydown(e, id) {
    if (e.isComposing) return; // IME 変換確定の Enter 等は奪わない
    if (window.SlashMenu && SlashMenu.handleKey(e)) return;
    const block = blocks[blockIndex(id)];
    if (!block) return;

    if (e.key === "Enter") {
      if (block.type === "code" || e.shiftKey) {
        // コード内 / Shift+Enter は改行を挿入
        e.preventDefault();
        document.execCommand("insertText", false, "\n");
        return;
      }
      e.preventDefault();
      splitBlock(block);
      return;
    }

    if (e.key === "Backspace" && !hasSelection()) {
      const el = contentEl(id);
      if (el && caretOffset(el) === 0) {
        e.preventDefault();
        backspaceAtStart(block);
      }
      return;
    }

    if (e.key === "ArrowUp") {
      const el = contentEl(id);
      if (el && caretOffset(el) === 0) {
        const prev = previousTextBlock(blockIndex(id));
        if (prev) {
          e.preventDefault();
          focusBlock(prev.id, "end");
        }
      }
      return;
    }

    if (e.key === "ArrowDown") {
      const el = contentEl(id);
      if (el && caretOffset(el) >= el.textContent.length) {
        const next = nextTextBlock(blockIndex(id));
        if (next) {
          e.preventDefault();
          focusBlock(next.id, 0);
        }
      }
    }
  }

  /** @param {number} index @returns {object | null} */
  function previousTextBlock(index) {
    for (let i = index - 1; i >= 0; i--) {
      if (!TEXTLESS_TYPES.has(blocks[i].type)) return blocks[i];
    }
    return null;
  }

  /** @param {number} index @returns {object | null} */
  function nextTextBlock(index) {
    for (let i = index + 1; i < blocks.length; i++) {
      if (!TEXTLESS_TYPES.has(blocks[i].type)) return blocks[i];
    }
    return null;
  }

  /** Enter: キャレット位置でブロックを分割する。 @param {object} block */
  async function splitBlock(block) {
    const el = contentEl(block.id);
    const offset = caretOffset(el);
    const text = el.textContent;

    // 空のリスト系ブロックで Enter → 段落に戻す (Notion の挙動)
    if (text === "" && block.type !== "paragraph") {
      patchBlock(block.id, { type: "paragraph" });
      rerenderBlock(block.id);
      focusBlock(block.id, 0);
      await save(block.id, { type: "paragraph" });
      return;
    }

    const before = text.slice(0, offset);
    const after = text.slice(offset);
    const newType = INHERIT_TYPES.has(block.type) ? block.type : "paragraph";

    patchBlock(block.id, { text: before });
    el.textContent = before;
    save(block.id, { text: before });
    await insertBlockAfter(block, newType, after);
  }

  /**
   * @param {object} block 挿入位置の直前ブロック
   * @param {string} type
   * @param {string} text
   * @param {boolean} [focus=true]
   * @returns {Promise<object | null>} 作成されたブロック
   */
  async function insertBlockAfter(block, type, text, focus = true) {
    try {
      const data = await API.createBlock(page.id, { type, text, after_id: block.id });
      const created = data.block;
      const index = blockIndex(block.id);
      blocks = [...blocks.slice(0, index + 1), created, ...blocks.slice(index + 1)];
      const row = root().querySelector(`[data-block-id="${block.id}"]`);
      row.after(renderBlock(created));
      if (focus) focusBlock(created.id, 0);
      return created;
    } catch (err) {
      App.toast("ブロックの作成に失敗しました: " + err.message);
      return null;
    }
  }

  /**
   * スラッシュメニュー選択の適用。コマンド文字列を除去しタイプ変換する。
   * @param {string} id
   * @param {string} type
   * @param {string} cleanText 「/コマンド」を取り除いた本文
   * @param {number} caretPos 復元するキャレット位置
   */
  async function applySlashCommand(id, type, cleanText, caretPos) {
    const block = blocks[blockIndex(id)];
    if (!block) return;

    if (type === "divider") {
      patchBlock(id, { text: cleanText });
      const el = contentEl(id);
      if (el) el.textContent = cleanText;
      await save(id, { text: cleanText });
      if (cleanText === "") {
        await convertToDivider(id);
        return;
      }
      const divider = await insertBlockAfter(blocks[blockIndex(id)], "divider", "", false);
      if (divider) await insertBlockAfter(divider, "paragraph", "");
      return;
    }

    patchBlock(id, { type, text: cleanText });
    rerenderBlock(id);
    focusBlock(id, Math.min(caretPos, cleanText.length));
    await save(id, { type, text: cleanText });
  }

  /** ページ末尾に段落を追加する。 */
  async function appendParagraph() {
    try {
      const data = await API.createBlock(page.id, { type: "paragraph", text: "" });
      blocks = [...blocks, data.block];
      root().appendChild(renderBlock(data.block));
      focusBlock(data.block.id, 0);
    } catch (err) {
      App.toast("ブロックの作成に失敗しました: " + err.message);
    }
  }

  /** Backspace (行頭): タイプ解除 → 直前と結合 の順で処理する。 @param {object} block */
  async function backspaceAtStart(block) {
    // 1. 段落以外はまず段落に戻す
    if (block.type !== "paragraph") {
      patchBlock(block.id, { type: "paragraph" });
      rerenderBlock(block.id);
      focusBlock(block.id, 0);
      await save(block.id, { type: "paragraph" });
      return;
    }

    const index = blockIndex(block.id);
    if (index === 0) return;

    const prev = blocks[index - 1];

    // 2. 直前が区切り線ならそれを削除
    if (prev.type === "divider") {
      await removeBlock(prev.id);
      focusBlock(block.id, 0);
      return;
    }

    // 3. 直前のブロックへ結合
    const mergeOffset = prev.text.length;
    const mergedText = prev.text + block.text;
    patchBlock(prev.id, { text: mergedText });
    const prevEl = contentEl(prev.id);
    if (prevEl) prevEl.textContent = mergedText;
    await Promise.all([save(prev.id, { text: mergedText }), removeBlock(block.id)]);
    focusBlock(prev.id, mergeOffset);
  }

  /** @param {string} id */
  async function removeBlock(id) {
    try {
      await API.deleteBlock(id);
      blocks = blocks.filter((b) => b.id !== id);
      const row = root().querySelector(`[data-block-id="${id}"]`);
      if (row) row.remove();
    } catch (err) {
      App.toast("ブロックの削除に失敗しました: " + err.message);
    }
  }

  /* ----------------------------------------------------------------------
     ドラッグ & ドロップによる並べ替え
     ---------------------------------------------------------------------- */
  /** @type {{id: string | null, afterId: string | null | undefined}} */
  const dragState = { id: null, afterId: undefined };

  function clearDropIndicator() {
    root()
      .querySelectorAll(".drop-target, .drop-target-top")
      .forEach((el) => el.classList.remove("drop-target", "drop-target-top"));
  }

  /** @param {DragEvent} e */
  function handleDragOver(e) {
    if (!dragState.id) return;
    const row = e.target.closest(".block");
    if (!row) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";

    const rect = row.getBoundingClientRect();
    const below = e.clientY > rect.top + rect.height / 2;
    clearDropIndicator();

    if (below) {
      dragState.afterId = row.dataset.blockId;
      row.classList.add("drop-target");
    } else {
      const index = blockIndex(row.dataset.blockId);
      dragState.afterId = index > 0 ? blocks[index - 1].id : null;
      if (index > 0) {
        const prevRow = root().querySelector(`[data-block-id="${blocks[index - 1].id}"]`);
        if (prevRow) prevRow.classList.add("drop-target");
      } else {
        row.classList.add("drop-target-top");
      }
    }
  }

  /** @param {DragEvent} e */
  async function handleDrop(e) {
    if (!dragState.id || dragState.afterId === undefined) return;
    e.preventDefault();
    const id = dragState.id;
    const afterId = dragState.afterId === id ? undefined : dragState.afterId;
    clearDropIndicator();
    if (afterId === undefined) return;

    const index = blockIndex(id);
    // 同じ位置へのドロップは無視
    if ((index > 0 && blocks[index - 1].id === afterId) || (index === 0 && afterId === null)) {
      return;
    }

    try {
      await API.moveBlock(id, { after_id: afterId });
      const moved = blocks[index];
      const rest = blocks.filter((b) => b.id !== id);
      const insertAt = afterId === null ? 0 : rest.findIndex((b) => b.id === afterId) + 1;
      blocks = [...rest.slice(0, insertAt), moved, ...rest.slice(insertAt)];
      render();
    } catch (err) {
      App.toast("並べ替えに失敗しました: " + err.message);
    }
  }

  /* ----------------------------------------------------------------------
     初期化: 余白クリックで末尾に段落を追加 (Notion の挙動) + DnD
     ---------------------------------------------------------------------- */
  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("page-container").addEventListener("click", (e) => {
      if (e.target.id !== "page-container" || !page) return;
      const last = blocks[blocks.length - 1];
      if (last && !TEXTLESS_TYPES.has(last.type) && last.text === "") {
        focusBlock(last.id, 0);
      } else {
        appendParagraph();
      }
    });
    root().addEventListener("dragover", handleDragOver);
    root().addEventListener("drop", handleDrop);
  });

  return { open, focusFirstBlock, applySlashCommand, caretOffset };
})();
