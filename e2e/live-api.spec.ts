import { expect, test, type Page, type Route } from "@playwright/test";

const STOCK = {
  ticker: "TCS",
  exchange: "NSE",
  name: "Tata Consultancy Services",
  sector: "Information Technology",
  price_inr: "3042.25",
  debt_to_equity: "0.08",
  dividend_yield: "1.72",
  sentiment: 0.35,
  updated_at: "2026-08-01T09:30:00Z",
};

const SOURCE = {
  id: "doc-tcs-1",
  ticker: "TCS",
  kind: "fundamentals",
  title: "TCS fundamentals snapshot",
  url: "https://example.test/tcs-fundamentals",
  content: "TCS reports low leverage and an INR 3,042.25 market price.",
  published_at: "2026-08-01T09:00:00Z",
  content_hash: "hash-1",
  sentiment: 0.35,
  impact: "positive",
  event_tag: "fundamentals",
  mentioned_tickers: ["TCS"],
};

async function routeBackendContract(
  page: Page,
  capture: {
    persona?: Record<string, unknown>;
    logout?: boolean;
    followPath?: string;
    followPayload?: Record<string, unknown>;
    ingestPayload?: Record<string, unknown>;
  },
) {
  await page.route("**/api/**", async (route: Route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();

    if (path === "/api/v1/auth/me") {
      return route.fulfill({ json: { id: "google-1", email: "reviewer@example.com", name: "Reviewer" } });
    }
    if (path === "/api/v1/stocks") return route.fulfill({ json: [STOCK] });
    if (path === "/api/v1/persona" && method === "GET") {
      return route.fulfill({
        json: {
          user_id: "google-1",
          risk_tolerance: "conservative",
          dividend_focused: true,
          avoid_high_debt: true,
          max_debt_to_equity: "1.0",
          preferred_sectors: ["Information Technology"],
          excluded_sectors: [],
          horizon: "7 to 10 years",
          notes: ["Prefers durable cash flows"],
          version: 2,
          updated_at: "2026-08-01T09:00:00Z",
        },
      });
    }
    if (path === "/api/v1/persona" && method === "PATCH") {
      capture.persona = request.postDataJSON();
      return route.fulfill({ json: capture.persona });
    }
    if (path === "/api/sources") return route.fulfill({ json: [SOURCE] });
    if (path.endsWith("/follow") && method === "POST") {
      capture.followPath = path;
      capture.followPayload = request.postDataJSON();
      return route.fulfill({
        status: 201,
        json: {
          ticker: "SBIN",
          followed: true,
          ingestion: { ticker: "SBIN", inserted: 2, skipped: 0, sentiment: 0.1 },
          stock: {
            ...STOCK,
            ticker: "SBIN",
            exchange: "BSE",
            name: "State Bank of India",
            sector: "Banking",
            price_inr: "812.40",
          },
        },
      });
    }
    if (path === "/api/ingest" && method === "POST") {
      capture.ingestPayload = request.postDataJSON();
      return route.fulfill({
        json: { ticker: "SBIN", inserted: 0, skipped: 2, sentiment: 0.1 },
      });
    }
    if (path === "/api/v1/chat" && method === "POST") {
      return route.fulfill({
        json: {
          answer: "TCS shows low leverage at the cited market price [1].",
          citations: [
            {
              index: 1,
              document_id: SOURCE.id,
              title: SOURCE.title,
              url: SOURCE.url,
            },
          ],
          grounded: true,
          persona_updated: false,
          recommendations: [],
        },
      });
    }
    if (path === "/api/v1/auth/logout" && method === "POST") {
      capture.logout = true;
      return route.fulfill({ status: 204, body: "" });
    }
    return route.fulfill({ status: 404, json: { detail: "not mocked" } });
  });
}

test("adapts the canonical FastAPI contract and links citations to retrieved documents", async ({ page }) => {
  await routeBackendContract(page, {});
  await page.goto("/");

  await expect(page.getByText("Live data", { exact: true })).toBeVisible();
  await expect(page.getByText("TCS", { exact: true }).first()).toBeVisible();
  await expect(page.getByLabel("TCS current sample quote")).toContainText("₹3,042.25");
  await expect(page.locator("#investor-memory")).toContainText("Conservative");
  await expect(page.locator("#investor-memory")).toContainText("Dividend and quality");
  await page.getByLabel("Ask Artha about an Indian equity").fill("How does TCS fit?");
  await page.getByRole("button", { name: "Ask Artha" }).click();
  const answer = page.locator("article.message.assistant").last();
  await answer.getByRole("button", { name: "Open source 1" }).click();
  await expect(page.locator("#source-doc-tcs-1")).toHaveClass(/is-expanded/);
  await expect(page.locator("#source-doc-tcs-1")).toContainText("low leverage");
});

test("sends persona updates in the FastAPI schema and logs out with POST", async ({ page }) => {
  const capture: { persona?: Record<string, unknown>; logout?: boolean } = {};
  await routeBackendContract(page, capture);
  await page.goto("/");

  const memory = page.locator("#investor-memory");
  await memory.getByRole("button", { name: "Edit" }).click();
  await memory.getByLabel("Risk appetite").selectOption("Aggressive");
  await memory.getByLabel("Investment style").fill("Growth");
  await memory.getByLabel("Prioritise").fill("Technology, Momentum");
  await memory.getByLabel("Avoid").fill("High debt");
  await memory.getByRole("button", { name: "Save memory" }).click();

  await expect.poll(() => capture.persona).toMatchObject({
    risk_tolerance: "aggressive",
    dividend_focused: false,
    avoid_high_debt: true,
    preferred_sectors: ["Technology", "Momentum"],
  });

  await page.locator('summary[aria-label="Open account menu for Reviewer"]').click();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect.poll(() => capture.logout).toBe(true);
  await expect(page.getByRole("link", { name: "Sign in with Google" })).toBeVisible();
});

test("preserves BSE across follow, hydration, and manual refresh", async ({ page }) => {
  const capture: {
    followPath?: string;
    followPayload?: Record<string, unknown>;
    ingestPayload?: Record<string, unknown>;
  } = {};
  await routeBackendContract(page, capture);
  await page.goto("/");

  await page.getByLabel("Exchange").selectOption("BSE");
  await page.getByLabel("Add a ticker").fill("SBIN");
  await page.getByRole("button", { name: "Add", exact: true }).click();

  await expect.poll(() => capture.followPath).toBe("/api/v1/stocks/SBIN.BO/follow");
  await expect.poll(() => capture.followPayload).toMatchObject({ ticker: "SBIN.BO" });
  const sbin = page
    .locator('.stock-list[aria-label="Followed equities"]')
    .getByRole("button")
    .filter({ has: page.getByText("SBIN", { exact: true }) });
  await expect(sbin).toContainText("BSE / Banking");
  await expect(sbin).toContainText("₹812.40");

  await page.getByRole("button", { name: "Refresh" }).click();
  await expect.poll(() => capture.ingestPayload).toMatchObject({
    ticker: "SBIN.BO",
  });
});
