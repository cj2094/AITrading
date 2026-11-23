import { getDashboardCached } from "@/lib/binance";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const force = ["1", "true", "yes"].includes(
    (url.searchParams.get("fresh") || "0").toLowerCase(),
  );

  try {
    const payload = await getDashboardCached({ force });
    return Response.json(payload, {
      headers: { "cache-control": "no-store" },
    });
  } catch (err) {
    return Response.json(
      { error: err instanceof Error ? err.message : String(err) },
      { status: 502, headers: { "cache-control": "no-store" } },
    );
  }
}
