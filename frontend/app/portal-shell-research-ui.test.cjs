const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");

function source(name) {
  return readFileSync(join(__dirname, name), "utf8");
}

test("portal shell keeps account and exit in sidebar, not topbar", () => {
  const shell = source("portal-shell-components.tsx");
  const styles = source("styles.css");
  const topbar = shell.slice(shell.indexOf("export function PortalTopbarStatus"));

  assert.match(shell, /LogOut/);
  assert.match(shell, /aria-label="Çıkış yap"/);
  assert.match(shell, /<span>Çıkış<\/span>/);
  assert.doesNotMatch(topbar, /topbar-user/);
  assert.doesNotMatch(topbar, /compact-exit/);
  assert.match(styles, /\.portal-sidebar\.collapsed \.sidebar-exit span/);
});

test("research screen uses accountant-facing labels and clear empty guidance", () => {
  const research = source("portal-research-view.tsx");

  assert.match(research, /Araştırma kayıtları/);
  assert.match(research, /Ürün ve hizmet bilgileri, kaynaklar ve müşavir kararları/);
  assert.match(research, /Kaynak güveni/);
  assert.match(research, /Fiş kararına etkisi/);
  assert.match(research, /Neden kontrol gerekiyor\?/);
  assert.match(research, /Müşavir kararını kaydet/);
  assert.match(research, /Kalite ölçümü/);
  assert.match(research, /Araştırma sonucu oluştuğunda burada görünür/);
  assert.match(research, /className="research-field"/);
  assert.match(research, /disabled=\{!selectedProfile\}/);
  assert.doesNotMatch(research, /Research cache, kaynak politikası/);
});

test("empty document review tells accountant next action", () => {
  const workspace = source("portal-workspace-view.tsx");
  const reviewPanels = source("portal-review-panels.tsx");

  assert.match(workspace, /Bu filtrede belge yok\. Mükellef seçin veya filtreyi değiştirin\./);
  assert.match(reviewPanels, /İşlemek için listeden belge seçin\./);
});
