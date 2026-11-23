(() => {
  const $ = (id) => document.getElementById(id);

  const state = {
    timer: null,
    loading: false,
    lastPayload: null,
  };

  function clsPnl(v) {
    const n = Number(v);
    if (!Number.isFinite(n) || n === 0) return "mono";
    return n > 0 ? "mono pos" : "mono neg";
  }

  function setPill(el, text, kind) {
    el.textContent = text;
    el.className = `pill ${kind || ""}`.trim();
  }

  function renderHero(p) {
    const items = [
      {
        label: "AUM",
        value: `${p.aumText} USDT`,
        sub: `分润 ${p.profitSharingText}`,
      },
      {
        label: "带单保证金",
        value: `${p.marginText} USDT`,
        sub: `状态 ${p.status || "-"}`,
      },
      {
        label: "跟单人数",
        value: `${p.currentCopyCount}/${p.maxCopyCount}`,
        sub: `累计 ${p.totalCopyCount}`,
      },
      {
        label: "最近成交",
        value: p.lastTradeText || "-",
        sub: p.positionShow ? "仓位公开" : "仓位已隐藏",
      },
    ];
    $("heroStats").innerHTML = items
      .map(
        (it) => `
      <article class="stat">
        <div class="label">${it.label}</div>
        <div class="value">${it.value}</div>
        <div class="sub">${it.sub}</div>
      </article>`
      )
      .join("");
  }

  function renderExposure(rows, err) {
    const box = $("exposureTable");
    if (err) {
      box.innerHTML = `<div class="empty">敞口推算失败：${escapeHtml(err)}</div>`;
      return;
    }
    if (!rows || !rows.length) {
      box.innerHTML =
        '<div class="empty">当前推算为空仓，或最近成交不足以还原未平仓。</div>';
      return;
    }
    box.innerHTML = `
      <table>
        <thead>
          <tr>
            <th>时间</th><th>合约</th><th>方向</th>
            <th class="mono">数量</th><th class="mono">估均价</th>
            <th class="mono">最新成交价</th><th class="mono">相关单数</th>
          </tr>
        </thead>
        <tbody>
          ${rows
            .map(
              (r) => `
            <tr>
              <td class="mono">${r.lastTimeText}</td>
              <td>${r.symbol}</td>
              <td><span class="tag ${String(r.side).toLowerCase()}">${r.side}</span></td>
              <td class="mono">${r.qtyText}</td>
              <td class="mono">${r.avgEntryEstText}</td>
              <td class="mono">${r.lastPriceText}</td>
              <td class="mono">${r.orders}</td>
            </tr>`
            )
            .join("")}
        </tbody>
      </table>`;
  }

  function renderOrders(rows) {
    const box = $("ordersTable");
    if (!rows || !rows.length) {
      box.innerHTML = '<div class="empty">暂无订单</div>';
      return;
    }
    box.innerHTML = `
      <table>
        <thead>
          <tr>
            <th>时间</th><th>合约</th><th>动作</th>
            <th class="mono">数量</th><th class="mono">价格</th>
            <th class="mono">盈亏</th><th>类型</th>
          </tr>
        </thead>
        <tbody>
          ${rows
            .map(
              (r) => `
            <tr>
              <td class="mono">${r.timeText}</td>
              <td>${r.symbol}</td>
              <td>${r.action}</td>
              <td class="mono">${r.qtyText}</td>
              <td class="mono">${r.priceText}</td>
              <td class="${clsPnl(r.pnl)}">${r.pnlText}</td>
              <td>${r.type || "-"}</td>
            </tr>`
            )
            .join("")}
        </tbody>
      </table>`;
  }

  function renderCloses(rows) {
    const box = $("closesTable");
    if (!rows || !rows.length) {
      box.innerHTML = '<div class="empty">暂无平仓记录</div>';
      return;
    }
    box.innerHTML = `
      <table>
        <thead>
          <tr>
            <th>时间</th><th>合约</th><th>方向</th>
            <th class="mono">量</th><th class="mono">盈亏</th>
            <th class="mono">ROI</th><th class="mono">杠杆</th>
          </tr>
        </thead>
        <tbody>
          ${rows
            .map(
              (r) => `
            <tr>
              <td class="mono">${r.closedText}</td>
              <td>${r.symbol}</td>
              <td><span class="tag ${String(r.side).toLowerCase()}">${r.side}</span></td>
              <td class="mono">${r.volumeText}</td>
              <td class="${clsPnl(r.pnl)}">${r.pnlText}</td>
              <td class="${clsPnl(r.pnl)}">${r.roiText}</td>
              <td class="mono">${r.leverage || "-"}x</td>
            </tr>`
            )
            .join("")}
        </tbody>
      </table>`;
  }

  function escapeHtml(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function applyPayload(data) {
    state.lastPayload = data;
    const p = data.portfolio || {};
    $("name").textContent = p.name || "熬鹰资本";
    if (p.binanceUrl) {
      $("binanceLink").href = p.binanceUrl;
    }

    const watcher = data.watcher || {};
    setPill(
      $("watcherPill"),
      watcher.running ? "Watcher · 运行中" : "Watcher · 未运行",
      watcher.running ? "ok" : "warn"
    );

    const cache = data.cache || {};
    const cacheLabel = cache.stale
      ? `Cache · 陈旧 ${cache.age_sec ?? "-"}s`
      : cache.hit
        ? `Cache · 命中 ${cache.age_sec ?? 0}s`
        : "Cache · 新鲜拉取";
    setPill($("cachePill"), cacheLabel, cache.stale ? "warn" : "ok");
    setPill($("clockPill"), `更新 · ${data.generatedAtText || "-"}`);

    renderHero(p);
    renderExposure(data.exposure || [], data.exposureError);
    renderOrders(data.orders || []);
    renderCloses(data.closedPositions || []);

    const notes = (data.notes || []).join(" · ");
    $("notes").textContent = notes;

    const err = $("errorBox");
    if (cache.error) {
      err.hidden = false;
      err.textContent = `最近刷新失败，展示缓存：${cache.error}`;
    } else {
      err.hidden = true;
      err.textContent = "";
    }
  }

  async function refresh({ force = false } = {}) {
    if (state.loading) return;
    state.loading = true;
    document.body.classList.add("loading");
    $("refreshBtn").disabled = true;
    try {
      const url = force ? "/api/dashboard?fresh=1" : "/api/dashboard";
      const res = await fetch(url, { cache: "no-store" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      applyPayload(data);
    } catch (err) {
      const box = $("errorBox");
      box.hidden = false;
      box.textContent = `刷新失败：${err.message || err}`;
      if (!state.lastPayload) {
        $("heroStats").innerHTML =
          '<article class="stat"><div class="label">错误</div><div class="value">加载失败</div></article>';
      }
    } finally {
      state.loading = false;
      document.body.classList.remove("loading");
      $("refreshBtn").disabled = false;
    }
  }

  function schedule() {
    if (state.timer) {
      clearInterval(state.timer);
      state.timer = null;
    }
    if (!$("autoRefresh").checked) return;
    const sec = Number($("intervalSec").value || 15);
    state.timer = setInterval(() => refresh({ force: false }), sec * 1000);
  }

  $("refreshBtn").addEventListener("click", () => refresh({ force: true }));
  $("autoRefresh").addEventListener("change", schedule);
  $("intervalSec").addEventListener("change", schedule);

  refresh({ force: true }).then(schedule);
})();
