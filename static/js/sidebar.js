// pynotion — サイドバーのページツリー
const Sidebar = (() => {
  "use strict";

  const EXPANDED_KEY = "pynotion-expanded";

  const state = {
    /** @type {Array<object>} */
    tree: [],
    /** @type {Set<string>} */
    expanded: new Set(JSON.parse(localStorage.getItem(EXPANDED_KEY) || "[]")),
    /** @type {string | null} */
    activeId: null,
  };

  function treeRoot() {
    return document.getElementById("page-tree");
  }

  function persistExpanded() {
    localStorage.setItem(EXPANDED_KEY, JSON.stringify([...state.expanded]));
  }

  /** ツリーを API から再取得して描画する。 */
  async function refresh() {
    const data = await API.pageTree();
    state.tree = data.pages;
    render();
  }

  /** @param {string | null} id */
  function setActive(id) {
    state.activeId = id;
    render();
  }

  function render() {
    const root = treeRoot();
    root.innerHTML = "";
    if (state.tree.length === 0) {
      const hint = document.createElement("div");
      hint.className = "tree-empty text-small text-secondary";
      hint.textContent = "ページがありません";
      root.appendChild(hint);
      return;
    }
    state.tree.forEach((node) => root.appendChild(renderNode(node, 0)));
  }

  /**
   * @param {object} node ページツリーのノード
   * @param {number} depth ネストの深さ
   * @returns {HTMLElement}
   */
  function renderNode(node, depth) {
    const wrap = document.createElement("div");
    const row = document.createElement("div");
    const isExpanded = state.expanded.has(node.id);
    const hasChildren = node.children.length > 0;

    row.className = "tree-row" + (node.id === state.activeId ? " is-active" : "");
    row.style.paddingLeft = 8 + depth * 14 + "px";
    row.dataset.pageId = node.id;

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "tree-toggle";
    toggle.textContent = isExpanded ? "▾" : "▸";
    toggle.title = isExpanded ? "折りたたむ" : "展開する";
    toggle.style.visibility = hasChildren ? "visible" : "hidden";
    toggle.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleExpand(node.id);
    });

    const icon = document.createElement("span");
    icon.className = "tree-icon";
    icon.textContent = node.icon || "📄";

    const title = document.createElement("span");
    title.className = "tree-title";
    title.textContent = node.title || "無題";

    const actions = document.createElement("span");
    actions.className = "tree-actions";

    const addChild = document.createElement("button");
    addChild.type = "button";
    addChild.className = "icon-btn";
    addChild.textContent = "＋";
    addChild.title = "サブページを追加";
    addChild.addEventListener("click", async (e) => {
      e.stopPropagation();
      const created = await API.createPage({ parent_id: node.id });
      state.expanded.add(node.id);
      persistExpanded();
      await refresh();
      App.openPage(created.page.id);
    });

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "icon-btn";
    remove.textContent = "🗑";
    remove.title = "ゴミ箱へ移動";
    remove.addEventListener("click", async (e) => {
      e.stopPropagation();
      await API.deletePage(node.id);
      await refresh();
      App.onPageTrashed(node.id);
    });

    actions.append(addChild, remove);
    row.append(toggle, icon, title, actions);
    row.addEventListener("click", () => App.openPage(node.id));
    wrap.appendChild(row);

    if (isExpanded && hasChildren) {
      const children = document.createElement("div");
      children.className = "tree-children";
      node.children.forEach((child) => children.appendChild(renderNode(child, depth + 1)));
      wrap.appendChild(children);
    }
    return wrap;
  }

  /** @param {string} id */
  function toggleExpand(id) {
    if (state.expanded.has(id)) {
      state.expanded.delete(id);
    } else {
      state.expanded.add(id);
    }
    persistExpanded();
    render();
  }

  /**
   * ツリー内のタイトル/アイコン表示だけを更新する (再取得なし)。
   * @param {string} id
   * @param {{title?: string, icon?: string}} patch
   */
  function updateLabel(id, patch) {
    const apply = (nodes) => {
      for (const node of nodes) {
        if (node.id === id) {
          if (patch.title !== undefined) node.title = patch.title;
          if (patch.icon !== undefined) node.icon = patch.icon;
          return true;
        }
        if (apply(node.children)) return true;
      }
      return false;
    };
    apply(state.tree);
    render();
  }

  return { refresh, setActive, updateLabel };
})();
