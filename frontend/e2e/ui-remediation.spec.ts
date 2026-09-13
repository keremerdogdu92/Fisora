// File: frontend/e2e/ui-remediation.spec.ts
// Summary: Verifies responsive accountant portal remediation, client list/detail onboarding flows, dialogs, research navigation, and delegated client access.
import { expect, test, type Page } from "@playwright/test";

const readyForRealDataPayload = {
  pilot_sellable: true,
  production_ready: false,
  real_data_pilot: {
    allowed: true,
    status: "ready_for_restricted_live_pilot",
    access_mode: "restricted_network",
    blocking: [],
  },
  pilot_blocking: [],
  warnings: ["zirve_field_test_pending"],
  auth: { auth_mode: "session_required" },
  store_backend: "postgres",
  ai_provider: "groq",
};

const pilotClient = {
  client_id: "pilot-client",
  profile: {
    client_id: "pilot-client",
    title: "ARİF Pilot Test AŞ",
    tax_id: "1111111111",
  },
};

const pilotWorkspace = {
  client: pilotClient,
  portal_users: [
    { user_id: "pilot-user", display_name: "Pilot User", role: "client_user" },
  ],
  uploaded_documents: [],
  processing_jobs: [],
  export_packages: [],
  documents: [
    {
      document_ref: "invoice-ready-1",
      document_type: "purchase_invoice",
      export_status: "review_required",
      created_at: "2026-06-10T10:00:00Z",
      result: {
        file_name: "invoice-ready.pdf",
        invoice_type: "purchase_invoice",
        intake_category: "purchase_invoice",
        export_status: "review_required",
        issue_date: "2026-06-10",
        payable_total: "1200.00",
        provider_hint: "Pilot Vendor",
        product_line_hint: "Danismanlik",
        ai_classification_reason: "Pilot fatura otomatik siniflandi.",
        draft_lines: [
          { account_code: "770.01", description: "Danismanlik", debit: "1000.00", credit: "0.00" },
          { account_code: "191.01", description: "KDV", debit: "200.00", credit: "0.00" },
          { account_code: "320.01", description: "Tedarikci", debit: "0.00", credit: "1200.00" },
        ],
        review_reason_codes: ["mixed_vat_manual_review", "counterparty_title_token_overlap"],
      },
    },
  ],
};

const twoPeriodWorkspace = {
  ...pilotWorkspace,
  documents: [
    ...pilotWorkspace.documents,
    {
      ...pilotWorkspace.documents[0],
      document_ref: "invoice-previous-period",
      created_at: "2026-05-12T10:00:00Z",
      result: {
        ...pilotWorkspace.documents[0].result,
        file_name: "invoice-previous-period.pdf",
        issue_date: "2026-05-12",
      },
    },
  ],
};

async function setupAccountantSession(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem("fisora.office.session.v1", JSON.stringify({
      userId: "mali-musavir",
      role: "accountant",
      sessionToken: "accountant-session",
      storageScope: "local",
    }));
  });
  await page.context().route("**/phase0/store/auth/session", async (route) => {
    const headers = await route.request().allHeaders();
    await route.fulfill({
      json: {
        valid: true,
        user_id: headers["x-fisora-user-id"] || "mali-musavir",
        expires_at: "2026-12-31T22:00:00+00:00",
      },
    });
  });
}

async function setupPilotRoutes(page: Page, workspace = pilotWorkspace) {
  await setupAccountantSession(page);
  await page.route("**/phase0/store/system/readiness", async (route) => {
    await route.fulfill({ json: readyForRealDataPayload });
  });
  await page.route("**/phase0/store/clients", async (route) => {
    await route.fulfill({ json: { clients: [pilotClient] } });
  });
  await page.route("**/phase0/store/workspace/**", async (route) => {
    await route.fulfill({ json: workspace });
  });
  await page.route("**/phase0/store/research/profiles**", async (route) => {
    await route.fulfill({
      json: {
        profiles: [
          {
            kind: "brand",
            key: "pilot-vendor",
            title: "Pilot Vendor",
            summary: "English supplier summary.",
            confidence: 82,
          },
        ],
      },
    });
  });
  await page.route("**/phase0/store/research/benchmark/runs", async (route) => {
    await route.fulfill({ json: { runs: [] } });
  });
}

test("documents route has no horizontal overflow on desktop and mobile", async ({ page }) => {
  await setupPilotRoutes(page);

  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/portal/belgeler");
  await expect(page.locator(".document-review-toolbar")).toBeVisible();
  const desktopOverflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(desktopOverflow).toBeLessThanOrEqual(0);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/portal/belgeler");
  const mobileOverflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(mobileOverflow).toBeLessThanOrEqual(0);
});


test("empty bank and other workbench stay document-specific", async ({ page }) => {
  await setupPilotRoutes(page);
  await page.setViewportSize({ width: 1366, height: 768 });
  await page.goto("/portal-next");
  await page.getByRole("button", { name: "Çalışma Masası", exact: true }).click();

  const workTabs = page.locator(".portal-next-work-tabs");
  const bankTab = workTabs.getByRole("button", { name: /^Banka/ });
  const otherTab = workTabs.getByRole("button", { name: /^Diğer Belgeler/ });
  await expect(bankTab).toHaveClass(/empty/);
  await expect(otherTab).toHaveClass(/empty/);

  for (const item of [
    { tab: bankTab, queue: "Banka Ekstreleri", empty: "Bu dönemde banka ekstresi yok" },
    { tab: otherTab, queue: "Diğer Belgeler", empty: "Bu dönemde diğer belge yok" },
  ]) {
    await item.tab.click();
    await expect(page.locator(".portal-next-command-direction")).toHaveCount(0);
    await expect(page.locator(".portal-next-queue-head strong")).toHaveText(item.queue);
    await expect(page.locator(".workbench-context-state strong")).toHaveText(item.empty);
    await expect(page.locator(".focus-action")).toBeDisabled();
  }

  await workTabs.getByRole("button", { name: /^Faturalar/ }).click();
  await expect(page.locator(".portal-next-command-direction").first()).toBeVisible();
  await expect(page.locator(".portal-next-queue-head strong")).toHaveText("İncelenecek Faturalar");
});

test("mobile login keeps authentication first and remember control compact", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");

  const username = page.locator('input[autocomplete="username"]');
  await expect(username).toHaveValue("");
  await expect(username).toHaveAttribute("placeholder", "Kullanıcı adı veya e-posta");
  await username.fill("temporary-user");
  await page.locator(".role-card").nth(1).click();
  await expect(username).toHaveValue("");
  await page.locator('input[autocomplete="current-password"]').fill("test-password");
  await page.locator(".landing-login > .primary").click();
  await expect(page.locator(".decision-status")).toHaveText("Kullanıcı adı veya e-posta girin.");

  await expect(page.locator(".role-copy")).toBeHidden();
  await expect(page.locator(".gateway-identity-foot")).toBeHidden();

  const loginPanel = page.locator(".role-entry-panel");
  await expect(loginPanel).toBeVisible();
  const loginBox = await loginPanel.boundingBox();
  expect(loginBox).not.toBeNull();
  expect(loginBox?.y ?? 999).toBeLessThan(100);
  expect((loginBox?.y ?? 0) + (loginBox?.height ?? 999)).toBeLessThan(844);

  const remember = page.locator(".remember-session");
  const checkbox = remember.locator('input[type="checkbox"]');
  await expect(remember).toHaveCSS("display", "flex");
  await expect(remember).toHaveCSS("align-items", "center");
  const checkboxBox = await checkbox.boundingBox();
  expect(checkboxBox).not.toBeNull();
  expect(checkboxBox?.width ?? 999).toBeLessThanOrEqual(18);
  expect(checkboxBox?.height ?? 999).toBeLessThanOrEqual(18);

  await page.setViewportSize({ width: 1280, height: 900 });
  await expect(page.locator(".role-copy")).toBeVisible();
  const identityBox = await page.locator(".gateway-identity-panel").boundingBox();
  const authBox = await page.locator(".gateway-auth-shell").boundingBox();
  expect(identityBox).not.toBeNull();
  expect(authBox).not.toBeNull();
  expect(authBox?.x ?? 0).toBeGreaterThan(identityBox?.x ?? 999);
});

test("workspace backend failure does not stay as loading copy", async ({ page }) => {
  await setupAccountantSession(page);
  await page.route("**/phase0/store/clients", async (route) => {
    await route.fulfill({ status: 404, body: "not found" });
  });
  await page.route("**/phase0/store/system/readiness", async (route) => {
    await route.fulfill({ json: readyForRealDataPayload });
  });

  await page.goto("/portal/musavir");

  await expect(page.getByRole("status", { name: /Çalışma alanı alınamadı|Geçici çalışma verisi|Çalışma alanı boş/i }).first()).toBeVisible();
  await expect(page.getByText("Çalışma alanı yükleniyor")).toHaveCount(0);
});

test("topbar notification and help actions open visible panels", async ({ page }) => {
  await setupPilotRoutes(page);
  await page.goto("/portal/musavir");

  await page.getByRole("button", { name: /Bildirimler/ }).click();
  await expect(page.getByRole("dialog", { name: /Bildirimler/ })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: /Bildirimler/ })).toHaveCount(0);

  await page.getByRole("button", { name: /Yardım/ }).click();
  await expect(page.getByRole("dialog", { name: /Yardım/ })).toBeVisible();
});

test("mobile portal starts with content visible and opens menu as drawer", async ({ page }) => {
  await setupPilotRoutes(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/portal/belgeler");

  await expect(page.getByLabel("Müşavir menüsü")).toHaveAttribute("data-mobile-open", "false");
  await expect(page.locator(".document-review-toolbar")).toBeVisible();

  await page.getByRole("button", { name: /Menüyü aç/ }).click();
  await expect(page.getByLabel("Müşavir menüsü")).toHaveAttribute("data-mobile-open", "true");

  await page.keyboard.press("Escape");
  await expect(page.getByLabel("Müşavir menüsü")).toHaveAttribute("data-mobile-open", "false");
});

test("client management uses list/detail navigation and clear onboarding sections", async ({ page }) => {
  await setupPilotRoutes(page);
  await page.goto("/portal/mukellefler");

  await expect(page.getByLabel(/M.kellef listesi/)).toBeVisible();
  const clientSearch = page.getByPlaceholder(/M.kellef ara/);
  await clientSearch.fill("bulunmayan");
  await expect(page.getByText("Aramayla eşleşen mükellef bulunamadı")).toBeVisible();
  await expect(page.getByText("Henüz mükellef yok")).toHaveCount(0);
  await page.getByRole("button", { name: "Aramayı temizle" }).click();
  await expect(clientSearch).toHaveValue("");
  await expect(page.getByText("ARİF Pilot Test AŞ").first()).toBeVisible();
  await clientSearch.fill("ARIF");
  await expect(page.getByText("ARİF Pilot Test AŞ").first()).toBeVisible();
  await clientSearch.fill("");

  await page.getByRole("button", { name: /Yeni m.kellef/ }).first().click();
  await expect(page.locator(".tax-certificate-preview")).toBeVisible();
  await expect(page.locator(".client-onboarding-steps")).toBeVisible();
  await expect(page.locator(".client-step")).toHaveCount(3);
  await expect(page.locator(".client-step").nth(0)).toContainText(/Vergi levhas/);
  await expect(page.locator(".client-step").nth(1)).toContainText(/Hesap plan/);
  await expect(page.locator(".client-step").nth(2)).toContainText(/Portal eri/);
  await expect(page.locator(".file-drop-control").first()).toBeVisible();

  await page.getByRole("button", { name: /M.kellef listesi/ }).click();
  await expect(page.getByLabel(/M.kellef listesi/)).toBeVisible();
  await page.getByRole("button", { name: /G.r.nt.le/ }).click();
  await expect(page.locator(".client-v13-detail")).toBeVisible();
  await expect(page.getByText("ARİF Pilot Test AŞ").first()).toBeVisible();
  await expect(page.locator(".client-v13-chart-replace")).toBeVisible();
  await expect(page.getByRole("button", { name: /Se.ili belgeleri sil/i })).toHaveCount(0);
});

test("client list and detail keep the same selected-period document scope", async ({ page }) => {
  await setupPilotRoutes(page, twoPeriodWorkspace);
  await page.goto("/portal/mukellefler");

  const clientRow = page.getByRole("row").filter({ hasText: "1111111111" });
  await expect(clientRow.locator('[data-label="Belge"]')).toHaveText("1");
  await expect(clientRow.locator('[data-label="Bekleyen"]')).toHaveText("1 kontrol");
  await clientRow.getByRole("button", { name: /G.r.nt.le/ }).click();

  const invoiceMetric = page.getByLabel(/M.kellef belge .zeti/).locator("article").filter({ hasText: "Faturalar" });
  await expect(invoiceMetric.locator("strong")).toHaveText("1");
  await expect(invoiceMetric.locator("small")).toHaveText("1 kontrol");
});

test("Bilgi Havuzu uses Turkish fallback copy for English-only profiles", async ({ page }) => {
  await setupPilotRoutes(page);
  await page.goto("/portal/bilgi-havuzu");

  await expect(page.getByText(/Kaynak .*Turkceye|Kaynak .*Türkçeye|Kaynak .*TÃ¼rkÃ§eye/i)).toBeVisible();
  await expect(page.locator("body")).not.toContainText("Failed to fetch");
});

test("Bilgi Havuzu stays secondary under AI Ajanlari and legacy route opens its tab", async ({ page }) => {
  await setupPilotRoutes(page);
  await page.goto("/portal/ajanlar");

  const researchTab = page.getByRole("tab", { name: /Araştırma kayıtları/ });
  await expect(researchTab).toHaveAttribute("aria-selected", "false");
  await expect(page.getByLabel("Müşavir menüsü")).not.toContainText("Bilgi Havuzu");

  await researchTab.click();
  await expect(researchTab).toHaveAttribute("aria-selected", "true");
  await expect(page.getByText(/Kaynak .*Türkçeye/i)).toBeVisible();

  await page.goto("/portal/bilgi-havuzu");
  await expect(page.getByRole("tab", { name: /Araştırma kayıtları/ })).toHaveAttribute("aria-selected", "true");
});
test("accountant opens selected client portal in a delegated tab without return controls", async ({ page }) => {
  await setupAccountantSession(page);
  await page.context().route("**/phase0/store/system/readiness", async (route) => {
    await route.fulfill({ json: readyForRealDataPayload });
  });
  await page.context().route("**/phase0/store/clients", async (route) => {
    await route.fulfill({ json: { clients: [pilotClient] } });
  });
  await page.context().route("**/phase0/store/workspace/**", async (route) => {
    await route.fulfill({ json: pilotWorkspace });
  });
  await page.context().route("**/phase0/store/auth/delegated-client-session", async (route) => {
    await route.fulfill({
      json: {
        session_token: "delegated-session-1",
        delegated_by: "mali-musavir",
        delegated_client_id: "pilot-client",
        session: {
          user_id: "pilot-user",
          expires_at: "2026-07-02T22:00:00+00:00",
          delegated_by: "mali-musavir",
          delegated_client_id: "pilot-client",
        },
      },
    });
  });

  await page.goto("/portal/mukellefler");
  await page.getByRole("button", { name: /G.r.nt.le/ }).click();

  const popupPromise = page.waitForEvent("popup");
  await page.getByRole("button", { name: /M.kellef portal.n. a./ }).click();
  const popup = await popupPromise;
  await popup.waitForLoadState("domcontentloaded");

  await expect(popup).toHaveURL(/\/portal\/mukellef/);
  await expect(popup.getByText("ARİF Pilot Test AŞ").first()).toBeVisible();
  await expect(popup.getByText(/Müşavir vekaletinde|MÃ¼ÅŸavir vekaletinde|MÃƒÂ¼ÅŸavir vekaletinde|Musavir vekaletinde/i)).toBeVisible();
  await expect(popup.getByRole("button", { name: /Müşavir ekranına dön|MÃ¼ÅŸavir ekranÄ±na dÃ¶n|sekme kapat|kapat/i })).toHaveCount(0);
});
