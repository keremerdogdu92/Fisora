const assert = require("node:assert/strict");
const test = require("node:test");
const {
  buildNotificationViewModel,
  fetchPortalNotifications,
  markPortalNotificationRead,
  pendingNotificationCount,
} = require("./portal-notifications.js");

test("buildNotificationViewModel groups retention warning by client period", () => {
  const view = buildNotificationViewModel({
    notification_id: "retention:batch-1",
    kind: "retention",
    status: "pending",
    read_at: "2026-05-02T09:00:00Z",
    accounting_period: "2026-02",
    delete_on: "2026-05-31",
    document_count: 12,
  });

  assert.equal(view.badgeLabel, "12 belge");
  assert.equal(view.pending, true);
  assert.equal(view.read, true);
  assert.match(view.title, /Şubat 2026/);
  assert.equal(pendingNotificationCount([view]), 1);
});

test("notification read remains pending until lifecycle resolves", () => {
  const view = buildNotificationViewModel({ status: "warning_open", read_at: "2026-05-02" });
  assert.equal(view.read, true);
  assert.equal(view.pending, true);
  assert.equal(pendingNotificationCount([view]), 1);
});

test("notification API carries session and user headers", async () => {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    return { ok: true, async json() { return { items: [{ notification_id: "retention:1", accounting_period: "2026-02", document_count: 1 }] }; } };
  };
  const items = await fetchPortalNotifications({ apiBaseUrl: "http://api/", sessionToken: "token", userId: "accountant", fetchImpl });
  assert.equal(items[0].notificationId, "retention:1");
  assert.equal(calls[0].options.headers["X-Fisora-Session"], "token");
  assert.equal(calls[0].options.headers["X-Fisora-User-Id"], "accountant");
});

test("markPortalNotificationRead posts stable notification id", async () => {
  let request;
  const fetchImpl = async (url, options) => {
    request = { url, options };
    return { ok: true, async json() { return { status: "warning_open" }; } };
  };
  await markPortalNotificationRead({ apiBaseUrl: "http://api", notificationId: "retention:batch-1", userId: "accountant", fetchImpl });
  assert.equal(request.url, "http://api/phase0/store/notifications/retention%3Abatch-1/read");
  assert.equal(request.options.method, "POST");
});
