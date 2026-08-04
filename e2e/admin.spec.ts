import { expect, test } from "@playwright/test";

async function openMockedWorkspace(page: import("@playwright/test").Page, email: string) {
  let adminRequestCount = 0;
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/auth/me") {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ email, name: "Test user" }),
      });
      return;
    }
    if (url.pathname === "/api/v1/stocks" || url.pathname === "/api/v1/persona") {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
      return;
    }
    if (url.pathname === "/api/v1/admin/users") {
      adminRequestCount += 1;
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify([{ id: "user-1", email: "user@example.com", name: "User One" }]),
      });
      return;
    }
    await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
  });
  await page.goto("/");
  await expect(page.getByText("Live data", { exact: true })).toBeVisible();
  return () => adminRequestCount;
}

test.describe("admin visibility", () => {
  test("shows the admin section for the approved authenticated email", async ({ page }) => {
    const adminRequests = await openMockedWorkspace(page, "admin@example.invalid");

    await expect(page.getByRole("heading", { name: "Admin" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Reset profile and followed stocks for user@example.com" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Reset followed stocks for user@example.com" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Delete conversations for user@example.com" })).toBeVisible();
    expect(adminRequests()).toBe(1);
  });

  test("hides the admin section for a different authenticated email", async ({ page }) => {
    const adminRequests = await openMockedWorkspace(page, "someone@example.com");

    await expect(page.getByRole("heading", { name: "Admin" })).toHaveCount(0);
    expect(adminRequests()).toBe(0);
  });
});
