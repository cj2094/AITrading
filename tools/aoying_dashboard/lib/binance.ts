export const DEFAULT_PORTFOLIO_ID = "5075281354358777856";
export const DEFAULT_NAME = "熬鹰资本";

const LEAD_BASE =
  "https://www.binance.com/bapi/futures/v1/friendly/future/copy-trade/lead-portfolio";

const SHANGHAI_OFFSET_MS = 8 * 60 * 60 * 1000;

export class BinanceAPIError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "BinanceAPIError";
  }
}

type Json = Record<string, unknown>;

function asRecord(value: unknown): Json {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Json)
    : {};
}

export function shanghaiNowIso(): string {
  const d = new Date(Date.now() + SHANGHAI_OFFSET_MS);
  return d.toISOString().replace("Z", "+08:00");
}

export function shanghaiNowText(): string {
  const d = new Date(Date.now() + SHANGHAI_OFFSET_MS);
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  const ss = String(d.getUTCSeconds()).padStart(2, "0");
  return `${y}-${m}-${day} ${hh}:${mm}:${ss} CST`;
}

export function fmtTs(ms: unknown): string {
  const n = Number(ms);
  if (!Number.isFinite(n) || n <= 0) return "-";
  const d = new Date(n + SHANGHAI_OFFSET_MS);
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  const ss = String(d.getUTCSeconds()).padStart(2, "0");
  return `${y}-${m}-${day} ${hh}:${mm}:${ss} CST`;
}

export function fmtNum(value: unknown, digits = 4): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return "-";
  if (Math.abs(n) >= 1000) {
    return n.toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }
  return n.toFixed(digits);
}

function headers(portfolioId: string): HeadersInit {
  return {
    "User-Agent":
      "Mozilla/5.0 (compatible; AITrading-HaoyingDashboard/1.0; +https://github.com/cj2094/AITrading)",
    "Content-Type": "application/json",
    Accept: "application/json",
    clienttype: "web",
    Origin: "https://www.binance.com",
    Referer: `https://www.binance.com/zh-CN/copy-trading/lead-details/${portfolioId}`,
  };
}

async function sleep(ms: number): Promise<void> {
  await new Promise((r) => setTimeout(r, ms));
}

async function requestJson(
  portfolioId: string,
  method: "GET" | "POST",
  path: string,
  body?: Json,
  query?: Record<string, string>,
  retries = 4,
): Promise<unknown> {
  let url = `${LEAD_BASE}/${path.replace(/^\//, "")}`;
  if (query) {
    const qs = new URLSearchParams(query).toString();
    url = `${url}?${qs}`;
  }

  let lastError: Error | null = null;
  for (let attempt = 0; attempt < retries; attempt++) {
    try {
      const res = await fetch(url, {
        method,
        headers: headers(portfolioId),
        body: body ? JSON.stringify(body) : undefined,
        cache: "no-store",
      });
      const raw = await res.text();
      let payload: Json;
      try {
        payload = JSON.parse(raw) as Json;
      } catch {
        throw new BinanceAPIError(`invalid JSON from ${path}: ${raw.slice(0, 200)}`);
      }

      const code = String(payload.code ?? "");
      const busy =
        code === "11012005" ||
        code === "90801003" ||
        (payload.success === false &&
          String(payload.message ?? "")
            .toLowerCase()
            .includes("busy"));

      if (busy && attempt + 1 < retries) {
        lastError = new BinanceAPIError(
          `API busy ${path}: code=${code} msg=${String(payload.message ?? "")}`,
        );
        await sleep(Math.min(5 * (attempt + 1), 30) * 1000);
        continue;
      }

      if (!res.ok) {
        throw new BinanceAPIError(`HTTP ${res.status} ${path}: ${raw.slice(0, 300)}`);
      }
      if (payload.success === false) {
        throw new BinanceAPIError(
          `API failure ${path}: code=${payload.code} msg=${payload.message}`,
        );
      }
      return "data" in payload ? payload.data : payload;
    } catch (err) {
      lastError = err instanceof Error ? err : new Error(String(err));
      if (attempt + 1 < retries) {
        await sleep(Math.min(2 ** attempt, 20) * 1000);
        continue;
      }
    }
  }
  throw lastError ?? new BinanceAPIError(`request failed ${path}`);
}

export function actionLabel(order: Json): string {
  const side = String(order.side ?? "").toUpperCase();
  const posSide = String(order.positionSide ?? "").toUpperCase();
  if (posSide === "LONG") return side === "BUY" ? "开多/加多" : "平多/减多";
  if (posSide === "SHORT") return side === "SELL" ? "开空/加空" : "平空/减空";
  return `${side} ${posSide}`.trim();
}

function signedQtyDelta(order: Json): number {
  const qty = Number(order.executedQty ?? 0);
  if (!Number.isFinite(qty)) return 0;
  const side = String(order.side ?? "").toUpperCase();
  const posSide = String(order.positionSide ?? "").toUpperCase();
  if (posSide === "" || posSide === "BOTH") return side === "BUY" ? qty : -qty;
  if (posSide === "LONG") return side === "BUY" ? qty : -qty;
  if (posSide === "SHORT") return side === "SELL" ? qty : -qty;
  return 0;
}

async function detail(portfolioId: string): Promise<Json> {
  return asRecord(
    await requestJson(portfolioId, "GET", "detail", undefined, {
      portfolioId,
    }),
  );
}

async function orderHistory(
  portfolioId: string,
  page = 1,
  pageSize = 30,
): Promise<Json[]> {
  const data = asRecord(
    await requestJson(portfolioId, "POST", "order-history", {
      portfolioId,
      pageNumber: page,
      pageSize,
    }),
  );
  return Array.isArray(data.list) ? (data.list as Json[]) : [];
}

async function positionHistory(
  portfolioId: string,
  page = 1,
  pageSize = 20,
): Promise<Json[]> {
  const data = asRecord(
    await requestJson(portfolioId, "POST", "position-history", {
      portfolioId,
      pageNumber: page,
      pageSize,
    }),
  );
  return Array.isArray(data.list) ? (data.list as Json[]) : [];
}

export async function reconstructExposure(
  portfolioId: string,
  pageSize = 30,
  pages = 3,
): Promise<Json[]> {
  const closes = new Map<string, number>();
  for (let page = 1; page <= pages; page++) {
    const list = await positionHistory(portfolioId, page, pageSize);
    for (const pos of list) {
      const status = String(pos.status ?? "");
      if (status !== "All Closed" && status !== "Closed") continue;
      const symbol = String(pos.symbol ?? "");
      const side = String(pos.side ?? "").toUpperCase();
      const closedAt = Number(pos.closed ?? pos.updateTime ?? 0);
      const key = `${symbol}|${side}`;
      if (closedAt && closedAt > (closes.get(key) ?? 0)) closes.set(key, closedAt);
    }
  }

  const exposure = new Map<
    string,
    {
      symbol: string;
      side: string;
      qty: number;
      notional: number;
      last_price: number | null;
      last_time: number;
      orders: number;
    }
  >();

  for (let page = 1; page <= pages; page++) {
    const list = await orderHistory(portfolioId, page, pageSize);
    for (const order of list) {
      const symbol = String(order.symbol ?? "");
      let posSide = String(order.positionSide ?? "").toUpperCase();
      if (posSide === "BOTH") {
        posSide = signedQtyDelta(order) >= 0 ? "LONG" : "SHORT";
      }
      const closeSide = posSide === "LONG" ? "LONG" : "SHORT";
      let baseline = 0;
      for (const [key, ts] of closes.entries()) {
        const [sym, side] = key.split("|");
        if (sym === symbol && side.toUpperCase() === closeSide) {
          baseline = Math.max(baseline, ts);
        }
      }
      const orderTime = Number(order.orderTime ?? order.orderUpdateTime ?? 0);
      if (baseline && orderTime <= baseline) continue;
      const delta = signedQtyDelta(order);
      if (!delta) continue;
      const key = `${symbol}|${closeSide}`;
      const slot = exposure.get(key) ?? {
        symbol,
        side: closeSide,
        qty: 0,
        notional: 0,
        last_price: null as number | null,
        last_time: 0,
        orders: 0,
      };
      const qty = Number(order.executedQty ?? 0);
      const px = Number(order.avgPrice ?? 0);
      slot.qty += delta;
      slot.notional += Math.abs(qty) * px * (delta > 0 ? 1 : -1);
      slot.last_price = px;
      slot.last_time = Math.max(slot.last_time, orderTime);
      slot.orders += 1;
      exposure.set(key, slot);
    }
  }

  return [...exposure.values()]
    .filter((row) => Math.abs(row.qty) >= 1e-12)
    .map((row) => ({
      symbol: row.symbol,
      side: row.side,
      qty: row.qty,
      qtyText: fmtNum(row.qty),
      avgEntryEst: row.qty ? Math.abs(row.notional / row.qty) : null,
      avgEntryEstText: row.qty ? fmtNum(Math.abs(row.notional / row.qty), 6) : "-",
      lastPrice: row.last_price,
      lastPriceText: fmtNum(row.last_price, 6),
      lastTime: row.last_time,
      lastTimeText: fmtTs(row.last_time),
      orders: row.orders,
    }))
    .sort((a, b) => Number(b.lastTime) - Number(a.lastTime));
}

function serializeOrder(order: Json) {
  return {
    time: order.orderTime ?? order.orderUpdateTime,
    timeText: fmtTs(order.orderTime ?? order.orderUpdateTime),
    symbol: order.symbol,
    side: order.side,
    positionSide: order.positionSide,
    action: actionLabel(order),
    qty: order.executedQty,
    qtyText: fmtNum(order.executedQty),
    price: order.avgPrice,
    priceText: fmtNum(order.avgPrice, 6),
    pnl: order.totalPnl,
    pnlText: fmtNum(order.totalPnl, 2),
    type: order.type,
  };
}

function serializePosition(pos: Json) {
  const roi = Number(pos.roi);
  const roiPct = Number.isFinite(roi) ? roi * 100 : null;
  return {
    closed: pos.closed ?? pos.updateTime,
    closedText: fmtTs(pos.closed ?? pos.updateTime),
    symbol: pos.symbol,
    side: pos.side,
    status: pos.status,
    volume: pos.closedVolume,
    volumeText: fmtNum(pos.closedVolume),
    avgCost: pos.avgCost,
    avgClosePrice: pos.avgClosePrice,
    pnl: pos.closingPnl,
    pnlText: fmtNum(pos.closingPnl, 2),
    roi: pos.roi,
    roiText: roiPct == null ? "-" : `${fmtNum(roiPct, 2)}%`,
    leverage: pos.leverage,
  };
}

export async function buildDashboard(portfolioId = DEFAULT_PORTFOLIO_ID) {
  const d = await detail(portfolioId);
  const orders = (await orderHistory(portfolioId, 1, 30)).slice(0, 30);
  const positions = (await positionHistory(portfolioId, 1, 20)).slice(0, 20);

  let exposure: Json[] = [];
  let exposureError: string | null = null;
  try {
    exposure = await reconstructExposure(portfolioId, 30, 3);
  } catch (err) {
    exposureError = err instanceof Error ? err.message : String(err);
  }

  const profitShare = Number(d.profitSharingRate ?? 0) || 0;

  return {
    generatedAt: shanghaiNowIso(),
    generatedAtText: shanghaiNowText(),
    portfolio: {
      id: d.leadPortfolioId ?? portfolioId,
      name: d.nickname ?? DEFAULT_NAME,
      status: d.status,
      positionShow: d.positionShow,
      description: d.description ?? d.descTranslate,
      aum: d.aumAmount,
      aumText: fmtNum(d.aumAmount),
      marginBalance: d.marginBalance,
      marginText: fmtNum(d.marginBalance),
      copierPnl: d.copierPnl,
      copierPnlText: fmtNum(d.copierPnl),
      currentCopyCount: d.currentCopyCount,
      maxCopyCount: d.maxCopyCount,
      totalCopyCount: d.totalCopyCount,
      profitSharingRate: profitShare,
      profitSharingText: `${fmtNum(profitShare, 2)}%`,
      lastTradeTime: d.lastTradeTime,
      lastTradeText: fmtTs(d.lastTradeTime),
      binanceUrl: `https://www.binance.com/zh-CN/copy-trading/lead-details/${d.leadPortfolioId ?? portfolioId}`,
    },
    orders: orders.map(serializeOrder),
    closedPositions: positions.map(serializePosition),
    exposure,
    exposureError,
    notes: [
      "带单员隐藏了实时仓位；敞口由公开成交推算，仅供参考。",
      "数据来自币安公开 lead-portfolio 接口，无需 API Key。",
    ],
  };
}

type CacheEntry = {
  at: number;
  payload: Awaited<ReturnType<typeof buildDashboard>>;
};

const globalForCache = globalThis as typeof globalThis & {
  __haoyingDashCache?: CacheEntry | null;
};

export async function getDashboardCached(opts?: {
  force?: boolean;
  ttlMs?: number;
  portfolioId?: string;
}) {
  const ttlMs = opts?.ttlMs ?? 8_000;
  const force = opts?.force ?? false;
  const portfolioId = opts?.portfolioId ?? DEFAULT_PORTFOLIO_ID;
  const cached = globalForCache.__haoyingDashCache;

  if (!force && cached && Date.now() - cached.at < ttlMs) {
    return {
      ...cached.payload,
      cache: {
        hit: true,
        age_sec: Number(((Date.now() - cached.at) / 1000).toFixed(2)),
        ttl_sec: ttlMs / 1000,
      },
    };
  }

  try {
    const payload = await buildDashboard(portfolioId);
    globalForCache.__haoyingDashCache = { at: Date.now(), payload };
    return {
      ...payload,
      cache: { hit: false, age_sec: 0, ttl_sec: ttlMs / 1000 },
    };
  } catch (err) {
    if (cached) {
      return {
        ...cached.payload,
        cache: {
          hit: true,
          stale: true,
          age_sec: Number(((Date.now() - cached.at) / 1000).toFixed(2)),
          ttl_sec: ttlMs / 1000,
          error: err instanceof Error ? err.message : String(err),
        },
      };
    }
    throw err;
  }
}
