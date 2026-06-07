// pynotion — スラッシュコマンドメニュー
// 「/」入力でブロックタイプ選択メニューを表示する。
const SlashMenu = (() => {
  "use strict";

  const ITEMS = [
    { type: "paragraph", label: "テキスト", icon: "T", keywords: ["text", "paragraph"] },
    { type: "heading_1", label: "見出し1", icon: "H1", keywords: ["h1", "heading1", "midashi"] },
    { type: "heading_2", label: "見出し2", icon: "H2", keywords: ["h2", "heading2"] },
    { type: "heading_3", label: "見出し3", icon: "H3", keywords: ["h3", "heading3"] },
    { type: "to_do", label: "ToDo リスト", icon: "☐", keywords: ["todo", "task", "check"] },
    { type: "bulleted_list_item", label: "箇条書きリスト", icon: "•", keywords: ["bullet", "list", "ul"] },
    { type: "numbered_list_item", label: "番号付きリスト", icon: "1.", keywords: ["number", "ol"] },
    { type: "quote", label: "引用", icon: "❝", keywords: ["quote", "inyou"] },
    { type: "divider", label: "区切り線", icon: "―", keywords: ["divider", "hr", "kugiri"] },
    { type: "code", label: "コード", icon: "</>", keywords: ["code"] },
  ];

  /** @type {{blockId: string, slashOffset: number, filter: string, selected: number} | null} */
  let state = null;

  function isOpen() {
    return state !== null;
  }

  /** @param {string} blockId @returns {HTMLElement | null} */
  function contentEl(blockId) {
    const row = document.querySelector(`#editor [data-block-id="${blockId}"]`);
    return row ? row.querySelector(".block-content") : null;
  }

  /**
   * エディタの input イベントから毎回呼ばれる。
   * 「/」直後なら開き、開いている間はフィルタを更新する。
   * @param {string} blockId
   * @param {HTMLElement} el
   */
  function onInput(blockId, el) {
    const text = el.textContent;
    const caret = Editor.caretOffset(el);

    if (!state) {
      if (caret > 0 && text[caret - 1] === "/") {
        state = { blockId, slashOffset: caret - 1, filter: "", selected: 0 };
        renderMenu(el);
      }
      return;
    }

    // 「/」が消えた・キャレットが戻った場合は閉じる
    if (
      blockId !== state.blockId ||
      text[state.slashOffset] !== "/" ||
      caret <= state.slashOffset
    ) {
      close();
      return;
    }

    state = { ...state, filter: text.slice(state.slashOffset + 1, caret), selected: 0 };
    if (filteredItems().length === 0) {
      close();
      return;
    }
    renderMenu(el);
  }

  /** @returns {Array<object>} */
  function filteredItems() {
    if (!state || state.filter === "") return ITEMS;
    const q = state.filter.toLowerCase();
    return ITEMS.filter(
      (item) =>
        item.label.toLowerCase().includes(q) ||
        item.keywords.some((kw) => kw.startsWith(q))
    );
  }

  /**
   * エディタの keydown から呼ばれる。消費したら true。
   * @param {KeyboardEvent} e
   * @returns {boolean}
   */
  function handleKey(e) {
    if (!state || e.isComposing) return false;
    const items = filteredItems();

    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const delta = e.key === "ArrowDown" ? 1 : -1;
      state = {
        ...state,
        selected: (state.selected + delta + items.length) % items.length,
      };
      renderMenu(contentEl(state.blockId));
      return true;
    }
    if (e.key === "Enter" || e.key === "Tab") {
      e.preventDefault();
      choose(items[state.selected]);
      return true;
    }
    if (e.key === "Escape") {
      e.preventDefault();
      close();
      return true;
    }
    return false;
  }

  /** @param {object} item */
  function choose(item) {
    if (!state) return;
    const { blockId, slashOffset, filter } = state;
    const el = contentEl(blockId);
    close();
    if (!el) return;
    const text = el.textContent;
    const cleanText = text.slice(0, slashOffset) + text.slice(slashOffset + 1 + filter.length);
    Editor.applySlashCommand(blockId, item.type, cleanText, slashOffset);
  }

  /** @param {HTMLElement | null} anchor */
  function renderMenu(anchor) {
    removeMenu();
    if (!state || !anchor) return;
    const items = filteredItems();

    const menu = document.createElement("div");
    menu.className = "popover slash-menu";

    const heading = document.createElement("div");
    heading.className = "slash-menu-heading text-small text-secondary";
    heading.textContent = "ベーシック";
    menu.appendChild(heading);

    items.forEach((item, index) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "menu-item" + (index === state.selected ? " is-active" : "");
      btn.innerHTML = "";

      const icon = document.createElement("span");
      icon.className = "slash-menu-icon";
      icon.textContent = item.icon;

      const label = document.createElement("span");
      label.textContent = item.label;

      btn.append(icon, label);
      // mousedown でフォーカス喪失より先に選択を確定させる
      btn.addEventListener("mousedown", (e) => {
        e.preventDefault();
        choose(item);
      });
      menu.appendChild(btn);
    });

    const rect = anchor.getBoundingClientRect();
    menu.style.left = rect.left + "px";
    menu.style.top = Math.min(rect.bottom + 4, window.innerHeight - 320) + "px";
    document.getElementById("modal-root").appendChild(menu);
  }

  function removeMenu() {
    document.querySelectorAll(".slash-menu").forEach((el) => el.remove());
  }

  function close() {
    state = null;
    removeMenu();
  }

  document.addEventListener("click", (e) => {
    if (state && !e.target.closest(".slash-menu")) close();
  });

  return { onInput, handleKey, isOpen, close };
})();
