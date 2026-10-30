import { getComparisonReport, importComparisonReport, listComparisonReports } from "./api";
import { comparisonFixture } from "./comparison.test-support";

afterEach(() => vi.unstubAllGlobals());

it("uses authenticated no-store read requests and encodes the identifier", async () => {
  const fetcher = vi.fn(async () => Response.json({ items: [] }));
  vi.stubGlobal("fetch", fetcher);
  const controller = new AbortController();
  await listComparisonReports(controller.signal);
  await getComparisonReport("record/id", controller.signal);
  expect(fetcher).toHaveBeenNthCalledWith(1, "/api/v1/admin/rag/comparisons", expect.objectContaining({ credentials: "include", cache: "no-store", signal: controller.signal }));
  expect(fetcher).toHaveBeenNthCalledWith(2, "/api/v1/admin/rag/comparisons/record%2Fid", expect.objectContaining({ credentials: "include", cache: "no-store" }));
});

it("submits only the selected comparison JSON with the dedicated mutation marker", async () => {
  const fetcher = vi.fn(async () => Response.json(comparisonFixture()));
  vi.stubGlobal("fetch", fetcher);
  const payload = comparisonFixture().report;
  await importComparisonReport(payload);
  expect(fetcher).toHaveBeenCalledExactlyOnceWith("/api/v1/admin/rag/comparisons", expect.objectContaining({
    method: "POST", credentials: "include", cache: "no-store", body: JSON.stringify(payload),
    headers: { "content-type": "application/json", "x-comparison-request": "1" },
  }));
});
