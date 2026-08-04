import { expect, test as base, type Page } from "@playwright/test";

/**
 * Keeps the critical-flow suite independent from live providers and credentials.
 * The client should immediately settle into its built-in deterministic sample mode.
 */
export const test = base.extend({
  page: async ({ page }, activatePage) => {
    await page.route("**/api/**", async (route) => {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ error: "E2E deterministic demo mode" }),
      });
    });
    await activatePage(page);
  },
});

export { expect };

export async function openDemoWorkspace(page: Page) {
  await page.goto("/demo");
  await expect(page.getByText("Sample data", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Deterministic demo mode. No live data or production state will be changed."),
  ).toBeVisible();
}
