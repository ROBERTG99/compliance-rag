import { expect, test } from "@playwright/test";
import { POA, ask, expectAccessible, signIn } from "./helpers";

test("analyst asks, sees a verified cited answer, and opens the evidence by keyboard", async ({ page }) => {
  await signIn(page, "analyst");
  await expectAccessible(page);
  await ask(page, POA, "2026-10-16");
  const answer = page.getByRole("region", { name: "Answer" });
  await expect(answer).toContainText("90 days");
  await expect(answer).toHaveAttribute("aria-live", "polite");
  await expect(page.getByText("KYC-0042 v3")).toBeVisible();
  await expect(page.getByText("As of 2026-10-16")).toBeVisible();
  await expect(page.getByText("AI-generated")).toBeVisible();
  await expectAccessible(page);

  const chip = page.getByRole("link", { name: /citation 1: KYC-0042 v3/i });
  await chip.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("mark")).toContainText("90 days");
  await expect(page.getByText("KYC-0042 v3")).toBeVisible();
  await expectAccessible(page);

  await page.goBack();
  await page.getByRole("button", { name: "Helpful", exact: true }).click();
  await page.getByRole("button", { name: "Send feedback" }).click();
  await expect(page.getByText(/thanks/i)).toBeVisible();
});

test("asking as of 2025-12-31 cites the superseded version and the evidence warns about it", async ({ page }) => {
  await signIn(page, "analyst");
  await ask(page, POA, "2025-12-31");
  await expect(page.getByRole("region", { name: "Answer" })).toContainText("120 days");
  await expect(page.getByText("superseded", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: /citation 1/i }).first().click();
  await expect(page.getByRole("note", { name: /superseded/i })).toContainText("Current version v3");
  await expectAccessible(page);
});
