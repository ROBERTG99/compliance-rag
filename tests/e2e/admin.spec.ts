import { expect, test } from "@playwright/test";
import { expectAccessible, signIn } from "./helpers";

test("admin screens render with live data and pass axe", async ({ page }) => {
  await signIn(page, "admin");
  await page.getByRole("link", { name: "Ingestion jobs" }).click();
  await expect(page.getByRole("region", { name: "Index lag" })).toContainText(
    "Pending",
  );
  await expect(
    page.getByRole("table", { name: "Ingestion jobs" }),
  ).toBeVisible();
  await expectAccessible(page);

  await page.getByRole("link", { name: "Library" }).click();
  await expect(page.getByRole("list", { name: "Documents" })).toBeVisible();
  await expect(page.getByText(/Restricted ·/).first()).toBeVisible();
  await expectAccessible(page);
  await page.getByLabel("Search").fill("KYC-0042");
  await page.getByRole("link", { name: "KYC-0042" }).click();
  await expect(page.getByRole("list", { name: "Versions" })).toContainText(
    "In force",
  );
  await expectAccessible(page);

  await page.getByRole("link", { name: "Feedback review" }).click();
  await expect(
    page.getByRole("heading", { name: "Feedback review" }),
  ).toBeVisible();
  await expectAccessible(page);

  await page.getByRole("link", { name: "Evaluation" }).click();
  await expect(
    page
      .getByRole("heading", { name: "Evaluation" })
      .or(page.getByText("No evaluation report yet")),
  ).toBeVisible();
  await expectAccessible(page);
});
