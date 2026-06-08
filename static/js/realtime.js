// pynotion — リアルタイム同期クライアント (WebSocket)
// ページ単位のチャンネルを購読し、他クライアントのブロック変更とプレゼンスを受信する。
// 書き込みは REST が source of truth なので、ここでは送信せず受信に専念する。
const Realtime = (() => {
  "use strict";

  const RECONNECT_BASE_MS = 1000;
  const RECONNECT_MAX_MS = 15000;

  /** @type {WebSocket | null} */
  let socket = null;
  /** @type {string | null} */
  let pageId = null;
  let intentionalClose = false;
  let reconnectTimer = null;
  let attempts = 0;
  let everConnected = false;

  /** @param {string} id @returns {string} */
  function wsUrl(id) {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const cid = encodeURIComponent(API.clientId);
    return `${proto}://${location.host}/ws/pages/${id}/?client_id=${cid}`;
  }

  /** 指定ページの購読を開始する (既存接続は閉じる)。 @param {string} id */
  function connect(id) {
    disconnect();
    pageId = id;
    intentionalClose = false;
    attempts = 0;
    everConnected = false;
    open();
  }

  function open() {
    if (!pageId) return;
    try {
      socket = new WebSocket(wsUrl(pageId));
    } catch (_) {
      scheduleReconnect();
      return;
    }
    socket.addEventListener("open", onOpen);
    socket.addEventListener("message", onMessage);
    socket.addEventListener("close", onClose);
  }

  function onOpen() {
    attempts = 0;
    // 再接続時は切断中に取りこぼした変更へ追いつくため最新状態を取り直す
    if (everConnected && window.Editor && Editor.reloadCurrent) {
      Editor.reloadCurrent();
    }
    everConnected = true;
  }

  /** @param {MessageEvent} ev */
  function onMessage(ev) {
    let msg;
    try {
      msg = JSON.parse(ev.data);
    } catch (_) {
      return;
    }
    if (msg.kind === "block_event") {
      if (window.Editor && Editor.applyRemote) Editor.applyRemote(msg.action, msg.data);
    } else if (msg.kind === "presence") {
      if (window.App && App.setPresence) App.setPresence(msg.members || []);
    }
  }

  function onClose() {
    socket = null;
    if (intentionalClose) return;
    scheduleReconnect();
  }

  function scheduleReconnect() {
    clearTimeout(reconnectTimer);
    // 指数バックオフ (上限あり)
    const delay = Math.min(RECONNECT_BASE_MS * 2 ** attempts, RECONNECT_MAX_MS);
    attempts += 1;
    reconnectTimer = setTimeout(open, delay);
  }

  function disconnect() {
    intentionalClose = true;
    clearTimeout(reconnectTimer);
    if (socket) {
      socket.close();
      socket = null;
    }
    if (window.App && App.setPresence) App.setPresence([]);
  }

  return { connect, disconnect };
})();

window.Realtime = Realtime;
