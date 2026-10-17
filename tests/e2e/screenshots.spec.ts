import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { LEGAL_ONLY, POA, ask, signIn } from "./helpers";

const IMAGES = path.resolve(__dirname, "../../docs/images");
const shot = (page: Page, name: string) => page.screenshot({ path: path.join(IMAGES, `${name}.png`) });

for (const theme of ["light", "dark"] as const) {
  test(`screens in ${theme} theme`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: theme });
    await signIn(page, "analyst");
    await ask(page, POA, "2026-10-16");
    await expect(page.getByText("KYC-0042 v3")).toBeVisible();
    await shot(page, `ask-${theme}`);
    await page.getByRole("link", { name: /citation 1/i }).first().click();
    await expect(page.locator("mark")).toBeVisible();
    await shot(page, `evidence-${theme}`);

    await page.getByRole("link", { name: "Library" }).click();
    await expect(page.getByRole("list", { name: "Documents" })).toBeVisible();
    await shot(page, `library-${theme}`);
    await page.getByLabel("Search").fill("KYC-0042");
    await page.getByRole("link", { name: "KYC-0042" }).click();
    await expect(page.getByRole("list", { name: "Versions" })).toBeVisible();
    await shot(page, `document-${theme}`);
    await page.getByRole("link", { name: "Evaluation" }).click();
    await expect(page.getByRole("heading", { name: "Evaluation" }).or(page.getByText("No evaluation report yet"))).toBeVisible();
    await shot(page, `evaluation-${theme}`);

    await signIn(page, "support");
    await ask(page, LEGAL_ONLY, "2026-10-16");
    await expect(page.getByRole("status", { name: "No answer" })).toBeVisible();
    await shot(page, `abstention-${theme}`);

    await signIn(page, "admin");
    await page.getByRole("link", { name: "Ingestion jobs" }).click();
    await expect(page.getByRole("table", { name: "Ingestion jobs" })).toBeVisible();
    await shot(page, `jobs-${theme}`);
    await page.getByRole("link", { name: "Feedback review" }).click();
    await expect(page.getByRole("heading", { name: "Feedback review" })).toBeVisible();
    await page.waitForLoadState("networkidle");
    await shot(page, `feedback-${theme}`);
  });
}

test("demo video of the main journey", async ({ page }) => {
  await signIn(page, "analyst");
  await ask(page, POA, "2026-10-16");
  await expect(page.getByText("KYC-0042 v3")).toBeVisible();
  await page.waitForTimeout(1500);
  await page.getByRole("link", { name: /citation 1/i }).first().click();
  await expect(page.locator("mark")).toBeVisible();
  await page.waitForTimeout(1500);
  await page.goBack();
  await page.getByRole("button", { name: "Helpful", exact: true }).click();
  await page.getByRole("button", { name: "Send feedback" }).click();
  await expect(page.getByText(/thanks/i)).toBeVisible();
  await page.waitForTimeout(1000);
  const video = page.video();
  await page.close();
  await video?.saveAs(path.join(IMAGES, "demo.webm"));
});
