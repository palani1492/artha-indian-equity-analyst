import { expect, test } from "@playwright/test";

async function openMockedWorkspace(page: import("@playwright/test").Page, email: string) {
  let adminRequestCount = 0;
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/auth/me") {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ email, name: "Test user", is_admin: email === "admin@example.invalid" }),
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

async function openAdminWorkspaceWithUsers(
  page: import("@playwright/test").Page,
  actionStatus = 204,
) {
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/auth/me") {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ id: "admin-id", email: "admin@example.invalid", name: "Admin", is_admin: true }) });
      return;
    }
    if (url.pathname === "/api/v1/admin/users") {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify([
          { id: "admin-id", email: "admin@example.invalid", name: "Admin" },
          { id: "user-1", email: "user@example.com", name: "User One" },
        ]),
      });
      return;
    }
    if (url.pathname.startsWith("/api/v1/admin/users/user-1/") && actionStatus !== 204) {
      await route.fulfill({ status: actionStatus, contentType: "application/json", body: JSON.stringify({ detail: actionStatus === 409 ? "self target" : "denied" }) });
      return;
    }
    await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
  });
  await page.goto("/");
  await expect(page.getByText("Live data", { exact: true })).toBeVisible();
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

  test("hides destructive actions for the signed-in administrator and keeps Admin last", async ({ page }) => {
    await openAdminWorkspaceWithUsers(page);

    const rail = page.locator(".context-rail");
    await expect(page.getByRole("button", { name: /for admin@example.invalid/ })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Reset profile and followed stocks for user@example.com" })).toBeVisible();
    await expect(rail.locator("section").last().getByRole("heading", { name: "Admin" })).toBeVisible();
  });

  test("shows specific authorization and self-target admin errors", async ({ page }) => {
    await openAdminWorkspaceWithUsers(page, 409);
    await page.getByRole("button", { name: "Skip" }).click();
    page.once("dialog", (dialog) => void dialog.accept());
    await page.getByRole("button", { name: "Reset followed stocks for user@example.com" }).click();
    await expect(page.locator(".admin-error")).toContainText("You cannot modify your own administrator account.");
  });
});
