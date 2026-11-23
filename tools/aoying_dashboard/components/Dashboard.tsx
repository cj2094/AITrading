"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type DashboardPayload = {
  generatedAtText?: string;
  portfolio?: {
    name?: string;
    status?: string;
    positionShow?: boolean;
    aumText?: string;
    marginText?: string;
    profitSharingText?: string;
    currentCopyCount?: number | string;
    maxCopyCount?: number | string;
    totalCopyCount?: number | string;
    lastTradeText?: string;
    binanceUrl?: string;
  };
  orders?: Array<Record<string, unknown>>;
  closedPositions?: Array<Record<string, unknown>>;
  exposure?: Array<Record<string, unknown>>;
  exposureError?: string | null;
  notes?: string[];
  cache?: {
    hit?: boolean;
    stale?: boolean;
    age_sec?: number;
    error?: string;
  };
};

function clsPnl(v: unknown): string {
  const n = Number(v);
  if (!Number.isFinite(n) || n === 0) return "mono";
  return n > 0 ? "mono pos" : "mono neg";
}

export function Dashboard() {
  const [data, setData] = useState<DashboardPayload | null>(null);
  const [error, setError] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [intervalSec, setIntervalSec] = useState(15);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async (force = false) => {
    setLoading(true);
    try {
      const url = force ? "/api/dashboard?fresh=1" : "/api/dashboard";
      const res = await fetch(url, { cache: "no-store" });
      const json = (await res.json()) as DashboardPayload & { error?: string };
      if (!res.ok) throw new Error(json.error || `HTTP ${res.status}`);
      setData(json);
      setError(json.cache?.error ? `最近刷新失败，展示缓存：${json.cache.error}` : "");
    } catch (err) {
      setError(`刷新失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh(true);
  }, [refresh]);

  useEffect(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    if (!autoRefresh) return;
    timerRef.current = setInterval(() => {
      void refresh(false);
    }, intervalSec * 1000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [autoRefresh, intervalSec, refresh]);

  const p = data?.portfolio ?? {};
  const cache = data?.cache ?? {};
  const cacheLabel = cache.stale
    ? `Cache · 陈旧 ${cache.age_sec ?? "-"}s`
    : cache.hit
      ? `Cache · 命中 ${cache.age_sec ?? 0}s`
      : "Cache · 新鲜拉取";

  return (
    <div className="shell">
      <header className="top">
        <div className="brand">
          <div className="mark" aria-hidden />
          <div>
            <p className="eyebrow">Binance Copy Trading Monitor</p>
            <h1>{p.name || "熬鹰资本"}</h1>
          </div>
        </div>
        <div className="controls">
          <label className="toggle">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
            />
            <span>自动刷新</span>
          </label>
          <label className="interval">
            间隔
            <select
              value={intervalSec}
              onChange={(e) => setIntervalSec(Number(e.target.value))}
            >
              <option value={10}>10s</option>
              <option value={15}>15s</option>
              <option value={30}>30s</option>
              <option value={60}>60s</option>
            </select>
          </label>
          <button
            type="button"
            disabled={loading}
            onClick={() => void refresh(true)}
          >
            立即刷新
          </button>
        </div>
      </header>

      <section className="meta-row">
        <div className={`pill ${cache.stale ? "warn" : "ok"}`}>{cacheLabel}</div>
        <div className="pill">更新 · {data?.generatedAtText || "—"}</div>
        {p.binanceUrl ? (
          <a
            className="pill link"
            href={p.binanceUrl}
            target="_blank"
            rel="noreferrer"
          >
            币安带单页 ↗
          </a>
        ) : null}
      </section>

      <section className="hero-stats" aria-live="polite">
        <article className="stat">
          <div className="label">AUM</div>
          <div className="value">{p.aumText || "—"} USDT</div>
          <div className="sub">分润 {p.profitSharingText || "—"}</div>
        </article>
        <article className="stat">
          <div className="label">带单保证金</div>
          <div className="value">{p.marginText || "—"} USDT</div>
          <div className="sub">状态 {p.status || "-"}</div>
        </article>
        <article className="stat">
          <div className="label">跟单人数</div>
          <div className="value">
            {p.currentCopyCount ?? "-"}/{p.maxCopyCount ?? "-"}
          </div>
          <div className="sub">累计 {p.totalCopyCount ?? "-"}</div>
        </article>
        <article className="stat">
          <div className="label">最近成交</div>
          <div className="value" style={{ fontSize: 16 }}>
            {p.lastTradeText || "-"}
          </div>
          <div className="sub">{p.positionShow ? "仓位公开" : "仓位已隐藏"}</div>
        </article>
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>估算未平仓敞口</h2>
          <p>仓位已隐藏，以下由公开成交推算</p>
        </div>
        <div className="table-wrap">
          {data?.exposureError ? (
            <div className="empty">敞口推算失败：{data.exposureError}</div>
          ) : !data?.exposure?.length ? (
            <div className="empty">
              当前推算为空仓，或最近成交不足以还原未平仓。
            </div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>时间</th>
                  <th>合约</th>
                  <th>方向</th>
                  <th className="mono">数量</th>
                  <th className="mono">估均价</th>
                  <th className="mono">最新成交价</th>
                  <th className="mono">相关单数</th>
                </tr>
              </thead>
              <tbody>
                {data.exposure.map((r, i) => (
                  <tr key={`${String(r.symbol)}-${i}`}>
                    <td className="mono">{String(r.lastTimeText)}</td>
                    <td>{String(r.symbol)}</td>
                    <td>
                      <span className={`tag ${String(r.side).toLowerCase()}`}>
                        {String(r.side)}
                      </span>
                    </td>
                    <td className="mono">{String(r.qtyText)}</td>
                    <td className="mono">{String(r.avgEntryEstText)}</td>
                    <td className="mono">{String(r.lastPriceText)}</td>
                    <td className="mono">{String(r.orders)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>

      <section className="grid-2">
        <div className="panel">
          <div className="panel-head">
            <h2>最近订单</h2>
            <p>开 / 加 / 减 / 平</p>
          </div>
          <div className="table-wrap">
            {!data?.orders?.length ? (
              <div className="empty">暂无订单</div>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>时间</th>
                    <th>合约</th>
                    <th>动作</th>
                    <th className="mono">数量</th>
                    <th className="mono">价格</th>
                    <th className="mono">盈亏</th>
                    <th>类型</th>
                  </tr>
                </thead>
                <tbody>
                  {data.orders.map((r, i) => (
                    <tr key={`${String(r.time)}-${i}`}>
                      <td className="mono">{String(r.timeText)}</td>
                      <td>{String(r.symbol)}</td>
                      <td>{String(r.action)}</td>
                      <td className="mono">{String(r.qtyText)}</td>
                      <td className="mono">{String(r.priceText)}</td>
                      <td className={clsPnl(r.pnl)}>{String(r.pnlText)}</td>
                      <td>{String(r.type || "-")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">
            <h2>最近平仓</h2>
            <p>All Closed / Closed</p>
          </div>
          <div className="table-wrap">
            {!data?.closedPositions?.length ? (
              <div className="empty">暂无平仓记录</div>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>时间</th>
                    <th>合约</th>
                    <th>方向</th>
                    <th className="mono">量</th>
                    <th className="mono">盈亏</th>
                    <th className="mono">ROI</th>
                    <th className="mono">杠杆</th>
                  </tr>
                </thead>
                <tbody>
                  {data.closedPositions.map((r, i) => (
                    <tr key={`${String(r.closed)}-${i}`}>
                      <td className="mono">{String(r.closedText)}</td>
                      <td>{String(r.symbol)}</td>
                      <td>
                        <span className={`tag ${String(r.side).toLowerCase()}`}>
                          {String(r.side)}
                        </span>
                      </td>
                      <td className="mono">{String(r.volumeText)}</td>
                      <td className={clsPnl(r.pnl)}>{String(r.pnlText)}</td>
                      <td className={clsPnl(r.pnl)}>{String(r.roiText)}</td>
                      <td className="mono">{String(r.leverage || "-")}x</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </section>

      <footer className="foot">
        <span>{(data?.notes || []).join(" · ")}</span>
        {error ? <span className="error">{error}</span> : null}
      </footer>
    </div>
  );
}
