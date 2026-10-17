import { expect, test } from "@playwright/test";
import {
  LEGAL_ONLY,
  ask,
  expectAccessible,
  signIn,
  switchPersona,
} from "./helpers";

test("support gets the uniform abstention for a Legal-only policy", async ({
  page,
}) => {
  await signIn(page, "support");
  await ask(page, LEGAL_ONLY, "2026-10-16");
  const banner = page.getByRole("status", { name: "No answer" });
  await expect(banner).toContainText("I can't answer that");
  await expect(page.locator("main")).not.toContainText("CMP-0215");
  await expect(page.locator("main")).not.toContainText(
    /litigation hold policy/i,
  );
  await expectAccessible(page);
});

test("legal can answer the same question", async ({ page }) => {
  await signIn(page, "legal");
  await ask(page, LEGAL_ONLY, "2026-10-16");
  await expect(page.getByText(/CMP-0215 v\d/)).toBeVisible();
  await expectAccessible(page);
});

test("switching persona in-page never shows the previous identity's restricted data", async ({
  page,
}) => {
  await signIn(page, "legal");
  await ask(page, LEGAL_ONLY, "2026-10-16");
  await expect(page.getByText(/CMP-0215 v\d/)).toBeVisible();
  await page.getByRole("link", { name: "Library" }).click();
  await page.getByLabel("Search").fill("CMP-0215");
  await expect(page.getByRole("link", { name: "CMP-0215" })).toBeVisible();

  await switchPersona(page, "support"); // no reload: caches and the run must not survive the switch
  // wait until support's own result has loaded, then check what it shows
  await page.getByLabel("Search").fill("CMP-0215");
  await expect(
    page.getByText("No documents match these filters"),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "CMP-0215" })).toHaveCount(0);
  await page.getByRole("link", { name: "Ask" }).click();
  await expect(page.locator("main")).not.toContainText("CMP-0215");
  await expect(page.getByLabel("Question")).toHaveValue("");
});

test("admin screens are not found for other roles", async ({ page }) => {
  await signIn(page, "analyst");
  await expect(page.getByRole("link", { name: "Ingestion jobs" })).toHaveCount(
    0,
  );
  await page.goto("/jobs");
  await expect(
    page.getByRole("heading", { name: "Page not found" }),
  ).toBeVisible();
  await expectAccessible(page);
});
