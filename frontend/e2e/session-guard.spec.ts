import { expect, test } from "@playwright/test";

test("landing keeps role cards but removes duplicate direct portal links", async ({ page }) => {
  await page.goto("/");

  await expect(page.locator('nav[aria-label="Portal girişleri"]')).toHaveCount(0);
  await expect(page.locator(".role-card")).toHaveCount(2);
  await expect(page.locator(".role-card").first()).toContainText("Müşavir girişi");
  await expect(page.locator(".role-card").last()).toContainText("Mükellef girişi");
  await expect(page.getByLabel("Kullanıcı")).toBeVisible();
  await expect(page.getByLabel("Şifre")).toBeVisible();
});

test("rejected stored session cannot open a locked portal route", async ({ page }) => {
  await page.addInitScript(() => {
    if (window.sessionStorage.getItem("fisora-test-stale-seeded")) return;
    window.sessionStorage.setItem("fisora-test-stale-seeded", "true");
    window.localStorage.setItem("fisora.office.session.v1", JSON.stringify({
      userId: "omer-yagci",
      role: "accountant",
      sessionToken: "stale-session",
      storageScope: "local",
    }));
  });
  await page.route("**/phase0/store/auth/session", async (route) => {
    await route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ detail: { reason: "session_not_found" } }),
    });
  });

  await page.goto("/portal/musavir");

  await expect(page).toHaveURL("/");
  await expect(page.locator(".portal-main-shell")).toHaveCount(0);
  await expect(page.locator(".role-card")).toHaveCount(2);
  const storedSession = await page.evaluate(() => window.localStorage.getItem("fisora.office.session.v1"));
  expect(storedSession).toBeNull();
});
