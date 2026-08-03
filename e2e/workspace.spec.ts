import type { Page } from "@playwright/test";
import { expect, openDemoWorkspace, test } from "./fixtures";

function followedTicker(page: Page, symbol: string) {
  return page
    .locator('.stock-list[aria-label="Followed equities"]')
    .getByRole("button")
    .filter({ has: page.getByText(symbol, { exact: true }) });
}

test.describe("Artha critical research flows", () => {
  test("loads the deterministic sample workspace and switches the active ticker", async ({ page }) => {
    await openDemoWorkspace(page);

    await expect(page.getByRole("heading", { name: "Followed equities" })).toBeVisible();
    await expect(page.getByText("Research desk / TCS", { exact: true })).toBeVisible();

    const reliance = followedTicker(page, "RELIANCE");
    await reliance.click();

    await expect(reliance).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByText("Research desk / RELIANCE", { exact: true })).toBeVisible();
    await expect(page.getByLabel("RELIANCE current quote")).toContainText("NSE: RELIANCE");
    await expect(page.getByLabel("RELIANCE current quote")).toContainText("₹1,398.40");
  });

  test("answers a research question with citations backed by visible sources", async ({ page }) => {
    await openDemoWorkspace(page);

    const composer = page.getByRole("form", { name: "Ask Artha" });
    await composer.getByLabel("Ask Artha about an Indian equity").fill("Compare TCS and Infosys");
    await composer.getByRole("button", { name: "Ask Artha" }).click();

    const userQuestion = page.locator("article.message.user").last();
    await expect(userQuestion).toContainText("Compare TCS and Infosys");

    const answer = page.locator("article.message.assistant").last();
    await expect(answer).toContainText("TCS has the stronger evidence fit");
    await expect(answer).toContainText("TCS currently has the clearer balance-sheet");
    await expect(answer.getByRole("button", { name: "Open source 1" })).toBeVisible();
    await expect(answer.getByRole("button", { name: "Open source 2" })).toBeVisible();
    await expect(answer.getByRole("button", { name: "Open source 3" })).toBeVisible();

    const evidenceRail = page.locator(".sources-panel");
    await expect(evidenceRail).toContainText("Current answer / TCS + INFY");
    await expect(evidenceRail.getByText("Sources used (3)", { exact: true })).toBeVisible();
    await expect(evidenceRail.locator("#source-tcs-results")).toContainText(
      "TCS / Exchange filing / TCS Investor Relations",
    );

    await answer.getByRole("button", { name: "Open source 2" }).click();
    const citedSource = page.locator("#source-tcs-results");
    await expect(citedSource).toHaveClass(/is-expanded/);
    await expect(citedSource).toContainText("TCS Investor Relations");
    await expect(citedSource.getByRole("link", { name: "Open source" })).toHaveAttribute(
      "href",
      /^https:\/\/www\.tcs\.com\//,
    );

    const reliance = followedTicker(page, "RELIANCE");
    await reliance.click();

    await expect(evidenceRail).toContainText("Ticker evidence / RELIANCE");
    await expect(evidenceRail.getByText("No sources retrieved", { exact: true })).toBeVisible();
    await expect(page.locator("#source-tcs-results")).toHaveCount(0);
  });

  test("discards a pending answer when the active ticker changes", async ({ page }) => {
    await openDemoWorkspace(page);

    const composer = page.getByRole("form", { name: "Ask Artha" });
    await composer.getByLabel("Ask Artha about an Indian equity").fill("Compare TCS and Infosys");
    await composer.getByRole("button", { name: "Ask Artha" }).click();
    await expect(page.locator(".sources-panel")).toContainText("Retrieving evidence for TCS + INFY");

    await followedTicker(page, "RELIANCE").click();
    await expect(page.getByText("Research desk / RELIANCE", { exact: true })).toBeVisible();
    await expect(page.locator(".sources-panel")).toContainText("Ticker evidence / RELIANCE");

    await page.waitForTimeout(500);
    await expect(page.locator("article.message.assistant")).toHaveCount(0);
    await expect(page.locator("#source-tcs-results")).toHaveCount(0);
  });

  test("updates and persists investor memory", async ({ page }) => {
    await openDemoWorkspace(page);

    const memory = page.locator("#investor-memory");
    await memory.getByRole("button", { name: "Edit" }).click();
    await memory.getByLabel("Risk appetite").selectOption("Conservative");
    await memory.getByLabel("Investment horizon").selectOption("5+ years");
    await memory.getByLabel("Investment style").selectOption("Dividend and quality");
    await memory.getByRole("button", { name: "Reliable dividends", exact: true }).click();
    await memory.getByRole("button", { name: "Save memory" }).click();

    await expect(page.locator('.context-notice[role="alert"]')).toContainText(
      "Investor memory updated for future research.",
    );
    await expect(memory).toContainText("Conservative");
    await expect(memory).toContainText("5+ years");
    await expect(memory).toContainText("Dividend and quality");
    await expect(memory).toContainText("Reliable dividends");

    await page.reload();
    await expect(page.getByText("Sample data", { exact: true })).toBeVisible();
    await expect(memory).toContainText("Conservative");
    await expect(memory).toContainText("5+ years");
  });

  test("follows a new BSE ticker and makes it active", async ({ page }) => {
    await openDemoWorkspace(page);

    await page.getByLabel("Exchange").selectOption("BSE");
    await page.getByLabel("Add a ticker").fill("sbin");
    await page.getByRole("button", { name: "Add", exact: true }).click();

    await expect(page.getByText("SBIN added. Fundamentals and news are queued.")).toBeVisible();
    const sbin = followedTicker(page, "SBIN");
    await expect(sbin).toBeVisible();
    await expect(sbin).toHaveAttribute("aria-pressed", "true");
    await expect(sbin).toContainText("BSE / New research coverage");
    await expect(page.getByText("Research desk / SBIN", { exact: true })).toBeVisible();
    await expect(page.getByLabel("SBIN current quote")).toContainText("Quote pending");
  });
});
