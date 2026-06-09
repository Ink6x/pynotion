// pynotion — データベースビュー(テーブル)。
// ページがデータベース化されているとき、本文エディタの下にテーブルを描画する。
// 値の検証・正規化・認可はサーバ側 (databases アプリ) が担い、ここは描画と
// 編集イベントの送信に専念する。
const Databases = (() => {
  "use strict";

  /** @type {{id:string, properties:Array, views:Array} | null} */
  let db = null;
  let container = null;
  // 描画世代トークン。ページを素早く切り替えたとき、古い render の await が
  // 後から完了して新しいテーブルを壊さないように使う。
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
      if (token !== renderToken) return; // 別ページへ切り替わった
      db = data.database;
      const view = await ensureTableView();
      if (token !== renderToken) return;
      const rows = (await API.viewRows(view.id)).rows || [];
      if (token !== renderToken) return;
      container.appendChild(buildTable(rows));
    } catch (err) {
      if (token !== renderToken) return;
      container.textContent = "データベースを読み込めませんでした";
    }
  }

  function hide() {
    renderToken++; // 進行中の render を無効化する
    if (container) {
      container.classList.add("hidden");
      container.innerHTML = "";
    }
    db = null;
  }

  /** 既定の table ビューが無ければ作る。 */
  async function ensureTableView() {
    const existing = (db.views || []).find((v) => v.type === "table");
    if (existing) return existing;
    const data = await API.createView(db.id, { type: "table", name: "テーブル" });
    // 破壊変更を避け、新しい db オブジェクトへ差し替える(immutable)。
    db = { ...db, views: [...(db.views || []), data.view] };
    return data.view;
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
    // 行操作 (削除)
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
    // text / number / date は input。number は数値へ変換して送る。
    const input = document.createElement("input");
    input.className = "db-input db-text";
    input.type = prop.type === "number" ? "number" : prop.type === "date" ? "date" : "text";
    input.value = value == null ? "" : value;
    const commit = () => {
      let out = input.value;
      if (prop.type === "number") out = input.value === "" ? null : Number(input.value);
      if ((prop.type === "date") && input.value === "") out = null;
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
      await reload();
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
    const pop = document.createElement("div");
    pop.className = "popover db-add-col-pop";

    const nameInput = document.createElement("input");
    nameInput.className = "db-col-name-input";
    nameInput.placeholder = "プロパティ名";

    const typeSel = document.createElement("select");
    typeSel.className = "db-col-type-input";
    Object.keys(TYPE_LABELS).forEach((t) => {
      const opt = document.createElement("option");
      opt.value = t;
      opt.textContent = TYPE_LABELS[t];
      typeSel.appendChild(opt);
    });

    const optsInput = document.createElement("input");
    optsInput.className = "db-col-options-input";
    optsInput.placeholder = "選択肢 (カンマ区切り)";
    optsInput.classList.add("hidden");
    typeSel.addEventListener("change", () => {
      const needsOptions = typeSel.value === "select" || typeSel.value === "multi_select";
      optsInput.classList.toggle("hidden", !needsOptions);
    });

    const add = document.createElement("button");
    add.type = "button";
    add.className = "btn btn-primary db-col-create";
    add.textContent = "追加";
    add.addEventListener("click", async () => {
      const name = nameInput.value.trim();
      if (!name) return;
      const payload = { name, type: typeSel.value };
      if (typeSel.value === "select" || typeSel.value === "multi_select") {
        const options = optsInput.value
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean);
        payload.config = { options };
      }
      try {
        await API.createProperty(db.id, payload);
        closePopovers();
        await reload();
      } catch (err) {
        App.toast(err.message || "プロパティを追加できませんでした");
      }
    });

    pop.append(nameInput, typeSel, optsInput, add);
    // getBoundingClientRect はビューポート基準なので、絶対配置のためスクロール量を足す。
    const rect = anchor.getBoundingClientRect();
    pop.style.left = rect.left + window.scrollX + "px";
    pop.style.top = rect.bottom + window.scrollY + 6 + "px";
    document.getElementById("modal-root").appendChild(pop);
    nameInput.focus();
    setTimeout(() => document.addEventListener("click", outside, { once: true }), 0);

    function outside(e) {
      if (!e.target.closest(".db-add-col-pop")) closePopovers();
      else document.addEventListener("click", outside, { once: true });
    }
  }

  function closePopovers() {
    document.querySelectorAll("#modal-root .db-add-col-pop").forEach((el) => el.remove());
  }

  /** 現在のデータベースを再取得して描画し直す。 */
  async function reload() {
    if (db) await render(container, db.id);
  }

  return { render, hide };
})();

window.Databases = Databases;
