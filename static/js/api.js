// pynotion — JSON API クライアント
// 全エンドポイントを {ok, data, error} 封筒前提でラップする。
const API = (() => {
  "use strict";

  /** @param {string} name @returns {string | null} */
  function getCookie(name) {
    const match = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
    return match ? decodeURIComponent(match[1]) : null;
  }

  // このタブ固有の識別子。書き込み時にサーバへ送り、WebSocket ブロードキャストの
  // 自己エコーを購読側で除去するために使う (Realtime.clientId と一致させる)。
  const clientId =
    (window.crypto && crypto.randomUUID && crypto.randomUUID()) ||
    "c" + Math.random().toString(36).slice(2) + Date.now().toString(36);

  /**
   * @param {string} method
   * @param {string} url
   * @param {object} [body]
   * @returns {Promise<object>} レスポンスの data 部
   */
  async function request(method, url, body) {
    const headers = { Accept: "application/json" };
    if (method !== "GET") {
      headers["Content-Type"] = "application/json";
      headers["X-CSRFToken"] = getCookie("csrftoken") || "";
      headers["X-Client-Id"] = clientId;
    }
    const res = await fetch(url, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    let json = null;
    try {
      json = await res.json();
    } catch (_) {
      /* JSON でないレスポンスは下で HTTP エラーとして扱う */
    }
    if (!res.ok || !json || json.ok === false) {
      const message = (json && json.error) || "HTTP " + res.status;
      const error = new Error(message);
      error.status = res.status;
      throw error;
    }
    return json.data;
  }

  return {
    clientId,
    // ページ
    pageTree: () => request("GET", "/api/pages/"),
    createPage: (payload) => request("POST", "/api/pages/", payload || {}),
    getPage: (id) => request("GET", `/api/pages/${id}/`),
    updatePage: (id, payload) => request("PATCH", `/api/pages/${id}/`, payload),
    deletePage: (id) => request("DELETE", `/api/pages/${id}/`),
    restorePage: (id) => request("POST", `/api/pages/${id}/restore/`, {}),
    permanentDeletePage: (id) => request("DELETE", `/api/pages/${id}/permanent/`),
    movePage: (id, payload) => request("POST", `/api/pages/${id}/move/`, payload),
    trashList: () => request("GET", "/api/pages/trash/"),
    search: (q) => request("GET", "/api/search/?q=" + encodeURIComponent(q)),
    // 共有
    listShares: (pageId) => request("GET", `/api/pages/${pageId}/shares/`),
    upsertShare: (pageId, payload) => request("POST", `/api/pages/${pageId}/shares/`, payload),
    removeShare: (pageId, userId) =>
      request("DELETE", `/api/pages/${pageId}/shares/${userId}/`),
    // ブロック
    createBlock: (pageId, payload) => request("POST", `/api/pages/${pageId}/blocks/`, payload),
    updateBlock: (id, payload) => request("PATCH", `/api/blocks/${id}/`, payload),
    deleteBlock: (id) => request("DELETE", `/api/blocks/${id}/`),
    moveBlock: (id, payload) => request("POST", `/api/blocks/${id}/move/`, payload),
  };
})();
