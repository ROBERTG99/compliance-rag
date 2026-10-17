import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";

export const POA = "What is the maximum age of a proof-of-address document?";
export const LEGAL_ONLY =
  "How long are complaint files under a litigation hold preserved after the hold is lifted?";

const SUBS: Record<string, string> = {
  analyst: "analyst@northwind.test",
  legal: "legal@northwind.test",
  support: "support@northwind.test",
  admin: "admin@northwind.test",
};

/** Sign in through the dev persona switcher (dev-oidc `/dev/token` via the same-origin proxy). */
export async function signIn(
  page: Page,
  persona: keyof typeof SUBS,
): Promise<void> {
  await page.goto("/");
  await page.getByLabel(/persona/i).selectOption(persona);
  await expect(page.getByText(SUBS[persona])).toBeVisible();
}

export async function ask(
  page: Page,
  question: string,
  asOf?: string,
): Promise<void> {
  await page.getByLabel("Question").fill(question);
  if (asOf) await page.getByLabel("As of").fill(asOf);
  await page.getByRole("button", { name: "Ask", exact: true }).click();
}

async function seriousViolations(page: Page): Promise<string[]> {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  return results.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map(
      (v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`,
    );
}

/** WCAG 2.2 AA via axe at 1280 px and 375 px: no serious or critical violations (BUILD.md §13). */
export async function expectAccessible(page: Page): Promise<void> {
  const size = page.viewportSize() ?? { width: 1280, height: 860 };
  expect(await seriousViolations(page)).toEqual([]);
  await page.setViewportSize({ width: 375, height: 800 });
  try {
    expect(await seriousViolations(page)).toEqual([]);
  } finally {
    await page.setViewportSize(size);
  }
}

/** Switch identity in-page (no reload), as a user of the dev persona switcher would. */
export async function switchPersona(
  page: Page,
  persona: keyof typeof SUBS,
): Promise<void> {
  await page.getByLabel(/persona/i).selectOption(persona);
  await expect(page.getByText(SUBS[persona])).toBeVisible();
}
