// pynotion — アプリ初期化とページ表示
const App = (() => {
  "use strict";

  const THEME_KEY = "pynotion-theme";
  const LAST_PAGE_KEY = "pynotion-last-page";
  const PRESET_ICONS = [
    "📄", "📝", "📚", "📦", "📅", "✅", "💡", "🚀",
    "🎯", "🧠", "🔥", "🌱", "🗂️", "🏠", "⭐", "❤️",
  ];

  /** @type {object | null} 現在開いているページ */
  let currentPage = null;
  /** @type {number | null} */
  let titleSaveTimer = null;

  async function init() {
    bindChrome();
    await Sidebar.refresh();
    const last = localStorage.getItem(LAST_PAGE_KEY);
    if (last) {
      try {
        await openPage(last);
        return;
      } catch (_) {
        localStorage.removeItem(LAST_PAGE_KEY);
      }
    }
    showEmpty();
  }

  function bindChrome() {
    document.getElementById("new-root-page").addEventListener("click", () => createPage());
    document.getElementById("empty-new-page").addEventListener("click", () => createPage());
    document.getElementById("theme-toggle").addEventListener("click", toggleTheme);

    const title = document.getElementById("page-title");
    title.addEventListener("input", scheduleTitleSave);
    title.addEventListener("keydown", (e) => {
      // タイトルで Enter → 本文へフォーカス移動 (Notion と同じ挙動)
      if (e.key === "Enter" && !e.isComposing) {
        e.preventDefault();
        if (window.Editor) Editor.focusFirstBlock();
      }
    });

    document.getElementById("page-icon").addEventListener("click", openIconPicker);
  }

  function toggleTheme() {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem(THEME_KEY, next);
  }

  /** @param {string} [parentId] */
  async function createPage(parentId) {
    const payload = parentId ? { parent_id: parentId } : {};
    const data = await API.createPage(payload);
    await Sidebar.refresh();
    await openPage(data.page.id);
    document.getElementById("page-title").focus();
  }

  /** @param {string} id */
  async function openPage(id) {
    const data = await API.getPage(id);
    currentPage = data.page;
    localStorage.setItem(LAST_PAGE_KEY, id);

    document.getElementById("page-empty").classList.add("hidden");
    document.getElementById("page-view").classList.remove("hidden");

    const title = document.getElementById("page-title");
    title.textContent = currentPage.title;
    renderIcon();

    Sidebar.setActive(id);
    if (window.Editor) Editor.open(currentPage, data.blocks);
  }

  function showEmpty() {
    currentPage = null;
    document.getElementById("page-view").classList.add("hidden");
    document.getElementById("page-empty").classList.remove("hidden");
    Sidebar.setActive(null);
  }

  /** ゴミ箱送りされたページが表示中なら空表示に戻す。 @param {string} id */
  function onPageTrashed(id) {
    if (currentPage && currentPage.id === id) {
      localStorage.removeItem(LAST_PAGE_KEY);
      showEmpty();
    }
  }

  function scheduleTitleSave() {
    if (titleSaveTimer) clearTimeout(titleSaveTimer);
    titleSaveTimer = setTimeout(saveTitle, 400);
  }

  async function saveTitle() {
    if (!currentPage) return;
    const text = document.getElementById("page-title").textContent;
    if (text === currentPage.title) return;
    currentPage = { ...currentPage, title: text };
    await API.updatePage(currentPage.id, { title: text });
    Sidebar.updateLabel(currentPage.id, { title: text });
  }

  function renderIcon() {
    const el = document.getElementById("page-icon");
    el.textContent = currentPage.icon || "";
    el.classList.toggle("is-empty", !currentPage.icon);
    el.title = currentPage.icon ? "アイコンを変更" : "アイコンを追加";
  }

  function openIconPicker(event) {
    closePopovers();
    const pop = document.createElement("div");
    pop.className = "popover icon-picker";

    const grid = document.createElement("div");
    grid.className = "icon-grid";
    PRESET_ICONS.forEach((emoji) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "icon-btn icon-choice";
      btn.textContent = emoji;
      btn.addEventListener("click", () => setIcon(emoji));
      grid.appendChild(btn);
    });

    const clear = document.createElement("button");
    clear.type = "button";
    clear.className = "menu-item is-danger";
    clear.textContent = "アイコンを削除";
    clear.addEventListener("click", () => setIcon(""));

    pop.append(grid, clear);
    const rect = event.currentTarget.getBoundingClientRect();
    pop.style.left = rect.left + "px";
    pop.style.top = rect.bottom + 8 + "px";
    document.getElementById("modal-root").appendChild(pop);

    setTimeout(() => {
      document.addEventListener("click", handleOutsideClick, { once: true });
    }, 0);
  }

  function handleOutsideClick(e) {
    if (!e.target.closest(".popover")) closePopovers();
    else document.addEventListener("click", handleOutsideClick, { once: true });
  }

  function closePopovers() {
    document.querySelectorAll("#modal-root .popover").forEach((el) => el.remove());
  }

  /** 一時的な通知を表示する。 @param {string} message */
  function toast(message) {
    const el = document.createElement("div");
    el.className = "toast";
    el.textContent = message;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3000);
  }

  /** @param {string} emoji 空文字で削除 */
  async function setIcon(emoji) {
    closePopovers();
    if (!currentPage) return;
    currentPage = { ...currentPage, icon: emoji };
    renderIcon();
    await API.updatePage(currentPage.id, { icon: emoji });
    Sidebar.updateLabel(currentPage.id, { icon: emoji });
  }

  document.addEventListener("DOMContentLoaded", init);

  return { openPage, createPage, onPageTrashed, showEmpty, closePopovers, toast };
})();
