import { expect, test } from "@playwright/test";
import { expectAccessible } from "./helpers";

test("sign in with authorization code + PKCE through the dev OIDC issuer", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Sign in to continue" }),
  ).toBeVisible();
  await expectAccessible(page);
  await page.getByRole("main").getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/localhost:8612\/authorize/);
  await page.getByRole("button", { name: /analyst@northwind\.test/ }).click();
  await page.waitForURL(/localhost:8600\/$/);
  await expect(page.getByText("analyst@northwind.test")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Ask a policy question" }),
  ).toBeVisible();
  await expect(page).toHaveTitle(/Ask · Northwind Compliance Assistant/);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(
    page.getByRole("heading", { name: "Sign in to continue" }),
  ).toBeVisible();
});
