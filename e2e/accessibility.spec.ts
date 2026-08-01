import { expect, openDemoWorkspace, test } from "./fixtures";

test.describe("Artha keyboard and accessibility smoke checks", () => {
  test("exposes landmarks, labels, status, and a working skip link", async ({ page }) => {
    await openDemoWorkspace(page);

    await expect(page.getByRole("main")).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Primary navigation" })).toBeVisible();
    await expect(page.getByRole("form", { name: "Ask Artha" })).toBeVisible();
    await expect(page.getByLabel("Research context")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Investor memory" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Sources used/ })).toBeVisible();

    const skipLink = page.getByRole("link", { name: "Skip to research" });
    await page.keyboard.press("Tab");
    await expect(skipLink).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/#research-thread$/);
  });

  test("supports multiline composition and Enter-to-send without a pointer", async ({ page }) => {
    await openDemoWorkspace(page);

    const question = page.getByLabel("Ask Artha about an Indian equity");
    await question.focus();
    await question.fill("Compare TCS");
    await page.keyboard.press("Shift+Enter");
    await page.keyboard.type("and Infosys");
    await expect(question).toHaveValue("Compare TCS\nand Infosys");
    await expect(page.locator("article.message.user")).toHaveCount(1);

    await page.keyboard.press("Enter");
    await expect(page.locator("article.message.user").last()).toContainText("Compare TCS");
    await expect(page.locator("article.message.user").last()).toContainText("and Infosys");
    await expect(page.locator("article.message.assistant").last()).toContainText(
      "TCS has the stronger evidence fit",
    );
  });
});
