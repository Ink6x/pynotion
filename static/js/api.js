// pynotion — JSON API クライアント
// 全エンドポイントを {ok, data, error} 封筒前提でラップする。
const API = (() => {
  "use strict";

  /** @param {string} name @returns {string | null} */
  function getCookie(name) {
    const match = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
    return match ? decodeURIComponent(match[1]) : null;
  }

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
      throw new Error(message);
    }
    return json.data;
  }

  return {
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
    // ブロック
    createBlock: (pageId, payload) => request("POST", `/api/pages/${pageId}/blocks/`, payload),
    updateBlock: (id, payload) => request("PATCH", `/api/blocks/${id}/`, payload),
    deleteBlock: (id) => request("DELETE", `/api/blocks/${id}/`),
    moveBlock: (id, payload) => request("POST", `/api/blocks/${id}/move/`, payload),
  };
})();
