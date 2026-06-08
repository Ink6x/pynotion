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
     共有モーダル
     ---------------------------------------------------------------------- */
  const ROLE_LABELS = {
    viewer: "閲覧者",
    commenter: "コメント可",
    editor: "編集者",
    full_access: "フルアクセス",
  };

  /** @returns {HTMLSelectElement} */
  function roleSelect(selected) {
    const select = document.createElement("select");
    select.className = "input share-role-select";
    Object.entries(ROLE_LABELS).forEach(([value, label]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      option.selected = value === selected;
      select.appendChild(option);
    });
    return select;
  }

  async function openShare() {
    const pageId = App.currentPageId();
    if (!pageId) return;

    const modal = document.createElement("div");
    modal.className = "modal";

    const header = document.createElement("div");
    header.className = "trash-header";
    header.textContent = "🔗 共有";

    const form = document.createElement("div");
    form.className = "share-form";
    const input = document.createElement("input");
    input.type = "text";
    input.className = "input";
    input.placeholder = "ユーザー名";
    const select = roleSelect("viewer");
    const add = document.createElement("button");
    add.type = "button";
    add.className = "btn btn-primary";
    add.textContent = "共有";
    form.append(input, select, add);

    const list = document.createElement("div");
    list.className = "share-list";

    modal.append(header, form, list);
    showModal(modal);
    input.focus();

    const submit = async () => {
      const username = input.value.trim();
      if (!username || add.disabled) return;
      add.disabled = true;
      try {
        await API.upsertShare(pageId, { username, role: select.value });
        input.value = "";
        await renderShares(pageId, list);
      } catch (err) {
        App.toast("共有に失敗しました: " + err.message);
      } finally {
        add.disabled = false;
      }
    };
    add.addEventListener("click", submit);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.isComposing) {
        e.preventDefault();
        submit();
      }
    });

    await renderShares(pageId, list);
  }

  /** @param {string} pageId @param {HTMLElement} list */
  async function renderShares(pageId, list) {
    try {
      const data = await API.listShares(pageId);
      list.innerHTML = "";
      if (data.shares.length === 0) {
        list.innerHTML =
          '<div class="search-hint text-small text-secondary">まだ誰にも共有されていません</div>';
        return;
      }
      data.shares.forEach((share) => list.appendChild(renderShareRow(pageId, share, list)));
    } catch (err) {
      closeModal();
      App.toast(
        err.status === 403
          ? "共有を管理できるのはフルアクセス権限のみです"
          : "共有リストの取得に失敗しました: " + err.message
      );
    }
  }

  /** @param {string} pageId @param {object} share @param {HTMLElement} list */
  function renderShareRow(pageId, share, list) {
    const row = document.createElement("div");
    row.className = "share-row";

    const name = document.createElement("span");
    name.className = "share-name";
    name.textContent = share.username;

    const select = roleSelect(share.role);
    select.addEventListener("change", async () => {
      try {
        await API.upsertShare(pageId, { username: share.username, role: select.value });
      } catch (err) {
        App.toast("ロール変更に失敗しました: " + err.message);
        await renderShares(pageId, list);
      }
    });

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "btn btn-ghost trash-action is-danger-text";
    remove.textContent = "解除";
    remove.addEventListener("click", async () => {
      try {
        await API.removeShare(pageId, share.user_id);
        await renderShares(pageId, list);
      } catch (err) {
        App.toast("共有解除に失敗しました: " + err.message);
      }
    });

    row.append(name, select, remove);
    return row;
  }

  /* ----------------------------------------------------------------------
     バージョン履歴モーダル
     ---------------------------------------------------------------------- */
  async function openHistory() {
    const pageId = App.currentPageId();
    if (!pageId) return;

    const modal = document.createElement("div");
    modal.className = "modal";

    const header = document.createElement("div");
    header.className = "trash-header";
    header.textContent = "🕘 バージョン履歴";

    const list = document.createElement("div");
    list.className = "history-list";

    modal.append(header, list);
    showModal(modal);

    await renderSnapshots(pageId, list);
  }

  /** @param {string} pageId @param {HTMLElement} list */
  async function renderSnapshots(pageId, list) {
    try {
      const data = await API.listSnapshots(pageId);
      list.innerHTML = "";
      if (data.snapshots.length === 0) {
        list.innerHTML =
          '<div class="search-hint text-small text-secondary">まだ履歴がありません。編集すると自動で保存されます。</div>';
        return;
      }
      data.snapshots.forEach((snap) =>
        list.appendChild(renderSnapshotRow(pageId, snap, list))
      );
    } catch (err) {
      closeModal();
      App.toast("履歴の取得に失敗しました: " + err.message);
    }
  }

  /** @param {string} pageId @param {object} snap @param {HTMLElement} list */
  function renderSnapshotRow(pageId, snap, list) {
    const row = document.createElement("div");
    row.className = "history-row";

    const meta = document.createElement("div");
    meta.className = "history-meta";
    const when = document.createElement("span");
    when.className = "history-when";
    when.textContent = formatDateTime(snap.created_at);
    const sub = document.createElement("span");
    sub.className = "history-sub text-small text-secondary";
    const by = snap.created_by ? ` · ${snap.created_by}` : "";
    sub.textContent = `${snap.block_count} ブロック${by}`;
    meta.append(when, sub);

    const restore = document.createElement("button");
    restore.type = "button";
    restore.className = "btn btn-ghost trash-action";
    restore.textContent = "復元";
    restore.addEventListener("click", () => restoreSnapshot(pageId, snap.id));

    row.append(meta, restore);
    return row;
  }

  /** @param {string} pageId @param {string} snapshotId */
  async function restoreSnapshot(pageId, snapshotId) {
    if (!window.confirm("このバージョンに復元しますか?(現在の状態も履歴に残ります)")) {
      return;
    }
    try {
      await API.restoreSnapshot(pageId, snapshotId);
      closeModal();
      await App.openPage(pageId); // 再構築されたブロックを反映
      App.toast("復元しました");
    } catch (err) {
      App.toast("復元に失敗しました: " + err.message);
    }
  }

  /** @param {string} iso @returns {string} */
  function formatDateTime(iso) {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    const pad = (n) => String(n).padStart(2, "0");
    return (
      `${d.getFullYear()}/${pad(d.getMonth() + 1)}/${pad(d.getDate())} ` +
      `${pad(d.getHours())}:${pad(d.getMinutes())}`
    );
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
    document.getElementById("share-button").addEventListener("click", openShare);
    document.getElementById("history-button").addEventListener("click", openHistory);
  });

  return { openSearch, openTrash, openShare, openHistory, closeModal };
})();
