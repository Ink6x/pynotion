// pynotion — データベースビュー(テーブル / ボード)。
// ページがデータベース化されているとき、本文エディタの下にビューを描画する。
// 値の検証・正規化・認可はサーバ側 (databases アプリ) が担い、ここは描画と
// 編集・並べ替えイベントの送信に専念する。
const Databases = (() => {
  "use strict";

  /** @type {{id:string, properties:Array, views:Array} | null} */
  let db = null;
  let container = null;
  /** @type {string | null} 現在表示中のビュー id */
  let activeViewId = null;
  // 描画世代トークン。ページ/ビューを素早く切り替えたとき、古い render の await が
  // 後から完了して新しい描画を壊さないように使う。
  let renderToken = 0;

  const TYPE_LABELS = {
    text: "テキスト",
    number: "数値",
    select: "選択",
    multi_select: "複数選択",
    date: "日付",
    checkbox: "チェック",
    relation: "リレーション",
  };

  /**
   * データベースを描画する。
   * @param {HTMLElement} el 描画先
   * @param {string} databaseId
   */
  async function render(el, databaseId) {
    const token = ++renderToken;
    container = el;
    container.classList.remove("hidden");
    container.innerHTML = "";
    try {
      const data = await API.getDatabase(databaseId);
      if (token !== renderToken) return;
      db = data.database;
      await ensureView();
      if (token !== renderToken) return;
      if (!activeViewId || !db.views.find((v) => v.id === activeViewId)) {
        activeViewId = db.views[0].id;
      }
      await renderShell(token);
    } catch (err) {
      if (token === renderToken) container.textContent = "データベースを読み込めませんでした";
    }
  }

  function hide() {
    renderToken++; // 進行中の render を無効化する
    if (container) {
      container.classList.add("hidden");
      container.innerHTML = "";
    }
    db = null;
    activeViewId = null;
  }

  /** ビューが 1 つも無ければ table ビューを作る。 */
  async function ensureView() {
    if ((db.views || []).length) return;
    const data = await API.createView(db.id, { type: "table", name: "テーブル" });
    db = { ...db, views: [data.view] }; // immutable に差し替え
  }

  /** 現在のデータベースを再取得して描画し直す。 */
  async function refresh() {
    if (db) await render(container, db.id);
  }

  // --- シェル(ビュー切替バー + 本体)--------------------------------------

  async function renderShell(token) {
    container.innerHTML = "";
    container.appendChild(buildSwitcher());
    const body = document.createElement("div");
    body.className = "db-view-body";
    container.appendChild(body);

    const view = db.views.find((v) => v.id === activeViewId);
    const data = await API.viewRows(view.id);
    if (token !== renderToken) return;
    if (view.type === "board") body.appendChild(buildBoard(view, data.groups || []));
    else body.appendChild(buildTable(data.rows || []));
  }

  function buildSwitcher() {
    const bar = document.createElement("div");
    bar.className = "db-views";
    db.views.forEach((v) => {
      const tab = document.createElement("button");
      tab.type = "button";
      tab.className = "db-view-tab";
      tab.dataset.view = v.id;
      if (v.id === activeViewId) tab.classList.add("active");
      tab.textContent = (v.type === "board" ? "🗂 " : "▦ ") + v.name;
      tab.addEventListener("click", () => {
        activeViewId = v.id;
        refresh();
      });
      bar.appendChild(tab);
    });
    const add = document.createElement("button");
    add.type = "button";
    add.className = "db-add-view";
    add.textContent = "＋ ビュー";
    add.addEventListener("click", (e) => openAddView(e.currentTarget));
    bar.appendChild(add);
    return bar;
  }

  // --- テーブル描画 ---------------------------------------------------------

  function buildTable(rows) {
    const table = document.createElement("table");
    table.className = "db-table";

    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    db.properties.forEach((prop) => headRow.appendChild(buildHeaderCell(prop)));
    headRow.appendChild(buildAddColumnCell());
    thead.appendChild(headRow);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    tbody.className = "db-rows";
    rows.forEach((row) => tbody.appendChild(buildRow(row)));
    table.appendChild(tbody);

    const foot = document.createElement("tfoot");
    const footRow = document.createElement("tr");
    const footCell = document.createElement("td");
    footCell.colSpan = db.properties.length + 1;
    const addRowBtn = document.createElement("button");
    addRowBtn.type = "button";
    addRowBtn.className = "db-add-row";
    addRowBtn.textContent = "＋ 新規";
    addRowBtn.addEventListener("click", onAddRow);
    footCell.appendChild(addRowBtn);
    footRow.appendChild(footCell);
    foot.appendChild(footRow);
    table.appendChild(foot);

    return table;
  }

  function buildHeaderCell(prop) {
    const th = document.createElement("th");
    th.className = "db-col";
    th.dataset.key = prop.key;
    const name = document.createElement("span");
    name.className = "db-col-name";
    name.textContent = prop.name;
    const type = document.createElement("span");
    type.className = "db-col-type";
    type.textContent = TYPE_LABELS[prop.type] || prop.type;
    th.append(name, type);
    return th;
  }

  function buildAddColumnCell() {
    const th = document.createElement("th");
    th.className = "db-col-add";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "db-add-col";
    btn.textContent = "＋";
    btn.title = "プロパティを追加";
    btn.addEventListener("click", (e) => openAddColumn(e.currentTarget));
    th.appendChild(btn);
    return th;
  }

  function buildRow(row) {
    const tr = document.createElement("tr");
    tr.className = "db-row";
    tr.dataset.row = row.id;
    db.properties.forEach((prop) => tr.appendChild(buildCell(row, prop)));
    const actions = document.createElement("td");
    actions.className = "db-cell-actions";
    const del = document.createElement("button");
    del.type = "button";
    del.className = "db-del-row";
    del.textContent = "🗑";
    del.title = "行を削除";
    del.addEventListener("click", () => onDeleteRow(row.id, tr));
    actions.appendChild(del);
    tr.appendChild(actions);
    return tr;
  }

  function buildCell(row, prop) {
    const td = document.createElement("td");
    td.className = "db-cell";
    td.dataset.key = prop.key;
    td.appendChild(buildEditor(row, prop));
    return td;
  }

  /** 型ごとのセル編集 UI を作る。変更は updateRow で永続化する。 */
  function buildEditor(row, prop) {
    const value = row.values ? row.values[prop.key] : null;
    const save = (newValue) => saveCell(row.id, prop.key, newValue);

    if (prop.type === "checkbox") {
      const input = document.createElement("input");
      input.type = "checkbox";
      input.className = "db-input db-checkbox";
      input.checked = value === true;
      input.addEventListener("change", () => save(input.checked));
      return input;
    }
    if (prop.type === "select") {
      const sel = document.createElement("select");
      sel.className = "db-input db-select";
      const empty = document.createElement("option");
      empty.value = "";
      empty.textContent = "—";
      sel.appendChild(empty);
      optionNames(prop).forEach((name) => {
        const opt = document.createElement("option");
        opt.value = name;
        opt.textContent = name;
        sel.appendChild(opt);
      });
      sel.value = value || "";
      sel.addEventListener("change", () => save(sel.value || null));
      return sel;
    }
    const input = document.createElement("input");
    input.className = "db-input db-text";
    input.type = prop.type === "number" ? "number" : prop.type === "date" ? "date" : "text";
    input.value = value == null ? "" : value;
    const commit = () => {
      let out = input.value;
      if (prop.type === "number") out = input.value === "" ? null : Number(input.value);
      if (prop.type === "date" && input.value === "") out = null;
      save(out);
    };
    input.addEventListener("blur", commit);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") input.blur();
    });
    return input;
  }

  function optionNames(prop) {
    const opts = (prop.config && prop.config.options) || [];
    return opts.map((o) => (typeof o === "string" ? o : o && o.name)).filter(Boolean);
  }

  // --- ボード描画 -----------------------------------------------------------

  function buildBoard(view, groups) {
    const board = document.createElement("div");
    board.className = "db-board";
    groups.forEach((group) => board.appendChild(buildLane(view, group)));
    return board;
  }

  function buildLane(view, group) {
    const lane = document.createElement("div");
    lane.className = "db-lane";
    lane.dataset.value = group.value == null ? "" : group.value;

    const header = document.createElement("div");
    header.className = "db-lane-header";
    const label = group.value == null ? "未設定" : group.value;
    header.textContent = `${label} (${group.rows.length})`;
    lane.appendChild(header);

    const list = document.createElement("div");
    list.className = "db-lane-cards";
    group.rows.forEach((row) => list.appendChild(buildCard(row)));
    lane.appendChild(list);

    const add = document.createElement("button");
    add.type = "button";
    add.className = "db-add-card";
    add.textContent = "＋ 新規";
    add.addEventListener("click", () => onAddCard(view, group.value));
    lane.appendChild(add);

    // ドロップ先 (グループ間 DnD)
    lane.addEventListener("dragover", (e) => {
      e.preventDefault();
      lane.classList.add("db-lane-over");
    });
    lane.addEventListener("dragleave", (e) => {
      // 子要素へ移っただけの dragleave では外さない(ハイライトのちらつき防止)
      if (!lane.contains(e.relatedTarget)) lane.classList.remove("db-lane-over");
    });
    lane.addEventListener("drop", (e) => onDropToLane(e, view, group.value, lane));
    return lane;
  }

  function buildCard(row) {
    const card = document.createElement("div");
    card.className = "db-card";
    card.draggable = true;
    card.dataset.row = row.id;
    card.textContent = cardLabel(row);
    card.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData("text/plain", row.id);
      e.dataTransfer.effectAllowed = "move";
    });
    return card;
  }

  /** カードの見出し: 最初の text プロパティ値、無ければ最初の非空値。 */
  function cardLabel(row) {
    const values = row.values || {};
    const textProp = db.properties.find((p) => p.type === "text");
    if (textProp && values[textProp.key]) return values[textProp.key];
    for (const p of db.properties) {
      const v = values[p.key];
      if (v !== "" && v != null && !(Array.isArray(v) && v.length === 0)) return String(v);
    }
    return "(無題)";
  }

  async function onDropToLane(e, view, laneValue, lane) {
    e.preventDefault();
    lane.classList.remove("db-lane-over");
    const rowId = e.dataTransfer.getData("text/plain");
    if (!rowId) return;
    try {
      // グループ値を更新 (未設定レーンは null)
      await API.updateRow(rowId, {
        values: { [view.group_by]: laneValue == null ? null : laneValue },
      });
      // レーン末尾へ並べ替え (fractional indexing 再利用)
      const cards = lane.querySelectorAll(".db-card");
      const last = cards.length ? cards[cards.length - 1] : null;
      if (last && last.dataset.row !== rowId) {
        await API.moveRow(rowId, { after_id: last.dataset.row });
      }
    } catch (err) {
      App.toast(err.message || "移動に失敗しました");
    } finally {
      // 成否に関わらずサーバ状態へ再同期する(updateRow 成功・moveRow 失敗で
      // UI が古いまま残るのを防ぐ)。
      await refresh();
    }
  }

  async function onAddCard(view, laneValue) {
    try {
      const values = {};
      if (laneValue != null) values[view.group_by] = laneValue;
      await API.createRow(db.id, { values });
      await refresh();
    } catch (err) {
      App.toast(err.message || "カードを追加できませんでした");
    }
  }

  // --- 変更ハンドラ ---------------------------------------------------------

  async function saveCell(rowId, key, value) {
    try {
      await API.updateRow(rowId, { values: { [key]: value } });
    } catch (err) {
      App.toast(err.message || "保存に失敗しました");
    }
  }

  async function onAddRow() {
    try {
      await API.createRow(db.id, { values: {} });
      await refresh();
    } catch (err) {
      App.toast(err.message || "行を追加できませんでした");
    }
  }

  async function onDeleteRow(rowId, tr) {
    try {
      await API.deleteRow(rowId);
      tr.remove();
    } catch (err) {
      App.toast(err.message || "削除に失敗しました");
    }
  }

  /** プロパティ追加ポップオーバー。名前・型・(選択型は)選択肢を入力。 */
  function openAddColumn(anchor) {
    closePopovers();
    const pop = mkPopover("db-add-col-pop");

    const nameInput = mkInput("db-col-name-input", "プロパティ名");
    const typeSel = document.createElement("select");
    typeSel.className = "db-col-type-input";
    Object.keys(TYPE_LABELS).forEach((t) => typeSel.appendChild(mkOption(t, TYPE_LABELS[t])));

    const optsInput = mkInput("db-col-options-input", "選択肢 (カンマ区切り)");
    optsInput.classList.add("hidden");
    typeSel.addEventListener("change", () => {
      const needs = typeSel.value === "select" || typeSel.value === "multi_select";
      optsInput.classList.toggle("hidden", !needs);
    });

    const add = mkButton("db-col-create", "追加", async () => {
      const name = nameInput.value.trim();
      if (!name) return;
      const payload = { name, type: typeSel.value };
      if (typeSel.value === "select" || typeSel.value === "multi_select") {
        payload.config = { options: splitOptions(optsInput.value) };
      }
      try {
        await API.createProperty(db.id, payload);
        closePopovers();
        await refresh();
      } catch (err) {
        App.toast(err.message || "プロパティを追加できませんでした");
      }
    });

    pop.append(nameInput, typeSel, optsInput, add);
    placePopover(pop, anchor);
    nameInput.focus();
  }

  /** ビュー追加ポップオーバー。table / board を選び、board は group_by を指定。 */
  function openAddView(anchor) {
    closePopovers();
    const pop = mkPopover("db-add-view-pop");

    const nameInput = mkInput("db-view-name-input", "ビュー名");
    const typeSel = document.createElement("select");
    typeSel.className = "db-view-type-input";
    typeSel.append(mkOption("table", "テーブル"), mkOption("board", "ボード"));

    const groupSel = document.createElement("select");
    groupSel.className = "db-view-group-input hidden";
    db.properties
      .filter((p) => p.type === "select")
      .forEach((p) => groupSel.appendChild(mkOption(p.key, p.name)));
    typeSel.addEventListener("change", () => {
      groupSel.classList.toggle("hidden", typeSel.value !== "board");
    });

    const add = mkButton("db-view-create", "追加", async () => {
      const payload = { name: nameInput.value.trim() || "ビュー", type: typeSel.value };
      if (typeSel.value === "board") {
        if (!groupSel.value) {
          App.toast("ボードには選択(select)プロパティが必要です");
          return;
        }
        payload.group_by = groupSel.value;
      }
      try {
        const data = await API.createView(db.id, payload);
        db = { ...db, views: [...db.views, data.view] };
        activeViewId = data.view.id;
        closePopovers();
        await refresh();
      } catch (err) {
        App.toast(err.message || "ビューを追加できませんでした");
      }
    });

    pop.append(nameInput, typeSel, groupSel, add);
    placePopover(pop, anchor);
    nameInput.focus();
  }

  // --- ポップオーバー小物 ---------------------------------------------------

  function mkPopover(cls) {
    const pop = document.createElement("div");
    pop.className = "popover db-pop " + cls;
    return pop;
  }

  function mkInput(cls, placeholder) {
    const el = document.createElement("input");
    el.className = cls;
    el.placeholder = placeholder;
    return el;
  }

  function mkOption(value, label) {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = label;
    return opt;
  }

  function mkButton(cls, label, onClick) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-primary " + cls;
    btn.textContent = label;
    btn.addEventListener("click", onClick);
    return btn;
  }

  function splitOptions(text) {
    return text
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
  }

  function placePopover(pop, anchor) {
    // getBoundingClientRect はビューポート基準なので、絶対配置のためスクロール量を足す。
    const rect = anchor.getBoundingClientRect();
    pop.style.left = rect.left + window.scrollX + "px";
    pop.style.top = rect.bottom + window.scrollY + 6 + "px";
    document.getElementById("modal-root").appendChild(pop);
    setTimeout(() => document.addEventListener("click", outside, { once: true }), 0);

    function outside(e) {
      if (!e.target.closest(".db-pop")) closePopovers();
      else document.addEventListener("click", outside, { once: true });
    }
  }

  function closePopovers() {
    document.querySelectorAll("#modal-root .db-pop").forEach((el) => el.remove());
  }

  return { render, hide };
})();

window.Databases = Databases;
