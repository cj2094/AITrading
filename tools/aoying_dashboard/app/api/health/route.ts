import { shanghaiNowIso } from "@/lib/binance";

export const dynamic = "force-dynamic";

export async function GET() {
  return Response.json(
    { ok: true, time: shanghaiNowIso() },
    { headers: { "cache-control": "no-store" } },
  );
}
