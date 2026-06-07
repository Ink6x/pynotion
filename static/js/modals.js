// pynotion — 検索 (Ctrl+K) とゴミ箱のモーダル
const Modals = (() => {
  "use strict";

  const SEARCH_DEBOUNCE_MS = 250;

  /** @type {{results: Array<object>, selected: number} | null} */
  let searchState = null;
  /** @type {number | null} */
  let searchTimer = null;

  function modalRoot() {
    return document.getElementById("modal-root");
  }

  function closeModal() {
    searchState = null;
    modalRoot().querySelectorAll(".modal-backdrop").forEach((el) => el.remove());
  }

  /** @param {HTMLElement} content */
  function showModal(content) {
    closeModal();
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.addEventListener("mousedown", (e) => {
      if (e.target === backdrop) closeModal();
    });
    backdrop.appendChild(content);
    modalRoot().appendChild(backdrop);
  }

  /* ----------------------------------------------------------------------
     検索モーダル
     ---------------------------------------------------------------------- */
  function openSearch() {
    const modal = document.createElement("div");
    modal.className = "modal";

    const inputWrap = document.createElement("div");
    inputWrap.className = "search-input-wrap";
    const input = document.createElement("input");
    input.type = "text";
    input.className = "input search-input";
    input.placeholder = "ページを検索…";
    inputWrap.appendChild(input);

    const results = document.createElement("div");
    results.className = "search-results";
    results.innerHTML =
      '<div class="search-hint text-small text-secondary">キーワードを入力してください</div>';

    modal.append(inputWrap, results);
    showModal(modal);
    searchState = { results: [], selected: 0 };
    input.focus();

    input.addEventListener("input", () => {
      if (searchTimer) clearTimeout(searchTimer);
      searchTimer = setTimeout(() => runSearch(input.value, results), SEARCH_DEBOUNCE_MS);
    });

    input.addEventListener("keydown", (e) => {
      if (e.isComposing || !searchState) return;
      const count = searchState.results.length;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        if (count === 0) return;
        const delta = e.key === "ArrowDown" ? 1 : -1;
        searchState = {
          ...searchState,
          selected: (searchState.selected + delta + count) % count,
        };
        renderResults(results);
      } else if (e.key === "Enter") {
        e.preventDefault();
        const page = searchState.results[searchState.selected];
        if (page) openResult(page.id);
      }
    });
  }

  /** @param {string} query @param {HTMLElement} container */
  async function runSearch(query, container) {
    if (!searchState) return;
    if (query.trim() === "") {
      searchState = { results: [], selected: 0 };
      container.innerHTML =
        '<div class="search-hint text-small text-secondary">キーワードを入力してください</div>';
      return;
    }
    try {
      const data = await API.search(query.trim());
      searchState = { results: data.pages, selected: 0 };
      renderResults(container);
    } catch (err) {
      App.toast("検索に失敗しました: " + err.message);
    }
  }

  /** @param {HTMLElement} container */
  function renderResults(container) {
    container.innerHTML = "";
    if (!searchState || searchState.results.length === 0) {
      container.innerHTML =
        '<div class="search-hint text-small text-secondary">結果がありません</div>';
      return;
    }
    searchState.results.forEach((page, index) => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "menu-item" + (index === searchState.selected ? " is-active" : "");

      const icon = document.createElement("span");
      icon.textContent = page.icon || "📄";
      const title = document.createElement("span");
      title.textContent = page.title || "無題";

      item.append(icon, title);
      item.addEventListener("click", () => openResult(page.id));
      container.appendChild(item);
    });
  }

  /** @param {string} pageId */
  function openResult(pageId) {
    closeModal();
    App.openPage(pageId);
  }

  /* ----------------------------------------------------------------------
     ゴミ箱モーダル
     ---------------------------------------------------------------------- */
  async function openTrash() {
    const modal = document.createElement("div");
    modal.className = "modal";

    const header = document.createElement("div");
    header.className = "trash-header";
    header.textContent = "🗑️ ゴミ箱";

    const list = document.createElement("div");
    list.className = "trash-list";

    modal.append(header, list);
    showModal(modal);
    await renderTrash(list);
  }

  /** @param {HTMLElement} list */
  async function renderTrash(list) {
    try {
      const data = await API.trashList();
      list.innerHTML = "";
      if (data.pages.length === 0) {
        list.innerHTML =
          '<div class="search-hint text-small text-secondary">ゴミ箱は空です</div>';
        return;
      }
      data.pages.forEach((page) => list.appendChild(renderTrashRow(page, list)));
    } catch (err) {
      App.toast("ゴミ箱の取得に失敗しました: " + err.message);
    }
  }

  /** @param {object} page @param {HTMLElement} list */
  function renderTrashRow(page, list) {
    const row = document.createElement("div");
    row.className = "trash-row";

    const label = document.createElement("span");
    label.className = "trash-title";
    label.textContent = (page.icon || "📄") + " " + (page.title || "無題");

    const restore = document.createElement("button");
    restore.type = "button";
    restore.className = "btn btn-ghost trash-action";
    restore.textContent = "復元";
    restore.addEventListener("click", async () => {
      try {
        await API.restorePage(page.id);
        await Sidebar.refresh();
        await renderTrash(list);
      } catch (err) {
        App.toast("復元に失敗しました: " + err.message);
      }
    });

    const destroy = document.createElement("button");
    destroy.type = "button";
    destroy.className = "btn btn-ghost trash-action is-danger-text";
    destroy.textContent = "完全に削除";
    destroy.addEventListener("click", async () => {
      try {
        await API.permanentDeletePage(page.id);
        await renderTrash(list);
      } catch (err) {
        App.toast("削除に失敗しました: " + err.message);
      }
    });

    row.append(label, restore, destroy);
    return row;
  }

  /* ----------------------------------------------------------------------
     初期化
     ---------------------------------------------------------------------- */
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      openSearch();
      return;
    }
    if (e.key === "Escape") closeModal();
  });

  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("search-button").addEventListener("click", openSearch);
    document.getElementById("trash-button").addEventListener("click", openTrash);
  });

  return { openSearch, openTrash, closeModal };
})();
