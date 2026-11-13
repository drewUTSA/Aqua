import { test, expect } from "@playwright/test";
import { setup } from "./fixture.mjs";
import { EMAIL_A, EMAIL_B, PASSWORD, VERIFY_PROOF, RESET_PROOF } from "../../frontend/checks/p05-browser-fixture.mjs";

let env;
test.beforeEach(async ({ page, context }) => { env = null; env = await setup(page, context); });
test.afterEach(async () => {
  if (!env) return; // Preserve a browser-launch failure without a cleanup error.
  await env.close(); expect(env.failures).toEqual([]); expect(env.external).toEqual([]);
});
const login = async page => {
  await page.goto(`${env.origin}/signin`);
  await page.getByLabel("Email address").fill(EMAIL_A);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByTestId("password-auth-submit").click();
  await expect(page.getByRole("button", { name: "Quick switch", exact: true })).toBeVisible();
};
const signout = async page => {
  if (!await page.getByRole("button", { name: "Account menu", exact: true }).isVisible()) await page.getByRole("button", { name: "Open navigation", exact: true }).click();
  await page.getByRole("button", { name: "Account menu", exact: true }).click();
  await page.getByRole("menuitem", { name: "Sign out", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Sign out", exact: true }).click();
};

test("storage-denied coordination and Google cleanup cannot break password sign-in/out", async ({ page }) => {
  await page.addInitScript(() => { window.BroadcastChannel = class { constructor() { throw new DOMException("Denied", "SecurityError"); } }; });
  await login(page);
  await page.evaluate(() => { window.google.accounts.id.disableAutoSelect = () => { throw new DOMException("Denied", "SecurityError"); }; });
  await signout(page);
  await expect(page.getByLabel("Email address")).toBeVisible();
  expect(env.fixture.email).toBeNull();
});

test("ordinary focus preserves a partially entered sign-in form", async ({ page }) => {
  await page.goto(`${env.origin}/signin`);
  await expect(page.getByTestId("password-auth-submit")).toBeEnabled();
  await page.getByLabel("Email address").fill(EMAIL_A);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.getByLabel("Password", { exact: true })).toHaveValue(PASSWORD);
  expect(env.fixture.count("/api/v1/auth/password-login")).toBe(0);
});

test("offline locks private access and reconnect revalidates without replaying a query", async ({ page }) => {
  await login(page);
  await page.evaluate(() => window.dispatchEvent(new Event("offline")));
  await expect(page.getByRole("button", { name: "Check connection again" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Quick switch", exact: true })).toBeHidden();
  await page.evaluate(() => window.dispatchEvent(new Event("online")));
  await expect(page.getByRole("button", { name: "Quick switch", exact: true })).toBeVisible();
  expect(env.fixture.queryCount()).toBe(0);
});

test("persisted pageshow rechecks a revoked session inside the focus debounce", async ({ page }) => {
  await login(page); env.fixture.email = null;
  const before = env.fixture.count("/api/auth/me", "GET");
  await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true })));
  await expect(page.getByLabel("Email address")).toBeVisible();
  expect(env.fixture.count("/api/auth/me", "GET")).toBeGreaterThan(before);
  expect(env.fixture.queryCount()).toBe(0);
});

test("a hung optional Google configuration does not block the password method", async ({ page }) => {
  env.fixture.google = "hold";
  await login(page);
  await env.fixture.release("google");
  await expect(page.getByRole("button", { name: "Quick switch", exact: true })).toBeVisible();
});

test("a hung session check reaches bounded recovery and an explicit retry succeeds", async ({ page }) => {
  env.blocked.add("/api/auth/me");
  await page.clock.install(); await page.goto(`${env.origin}/signin`);
  await expect.poll(() => env.attempts("/api/auth/me", "GET")).toBe(1);
  await page.clock.fastForward(31000);
  await expect(page.getByRole("button", { name: "Check connection again" })).toBeVisible();
  env.blocked.clear();
  await page.getByRole("button", { name: "Check connection again" }).click();
  await expect(page.getByTestId("password-auth-submit")).toBeEnabled();
});

test("an uncertain sign-out remains locked through timeout and reconnect", async ({ page }) => {
  await login(page); env.blocked.add("/api/auth/logout");
  await page.clock.install(); await signout(page);
  await expect.poll(() => env.attempts("/api/auth/logout")).toBe(1);
  await page.clock.fastForward(31000);
  await expect(page.getByTestId("signout-retry")).toBeVisible();
  await page.evaluate(() => window.dispatchEvent(new Event("online")));
  await expect(page.getByTestId("signout-retry")).toBeVisible();
  await expect(page.getByRole("button", { name: "Quick switch", exact: true })).toBeHidden();
  expect(env.attempts("/api/auth/logout")).toBe(1);
});

test("email verification scrubs its fragment and submits only after a deliberate action", async ({ page }) => {
  await page.goto(`${env.origin}/verify-email#token=${VERIFY_PROOF}`);
  await expect(page).toHaveURL(`${env.origin}/verify-email`);
  await expect(page.getByTestId("password-auth-submit")).toBeEnabled();
  expect(env.fixture.count("/api/v1/auth/email-verifications")).toBe(0);
  await page.getByLabel("New password", { exact: true }).fill(PASSWORD);
  await page.getByLabel("Confirm new password", { exact: true }).fill(PASSWORD);
  await page.getByTestId("password-auth-submit").click();
  await expect(page.getByRole("heading", { name: "Your account is ready" })).toBeVisible();
  expect(env.fixture.count("/api/v1/auth/email-verifications")).toBe(1);
  expect(env.fixture.email).toBeNull();
});

test("a stalled reset is bounded, locks the cached session and never automatically replays", async ({ page, context }) => {
  env.fixture.email = EMAIL_A; env.blocked.add("/api/v1/auth/password-resets");
  await context.addCookies([{ name: "aqua-fixture", value: "session", url: env.origin }]);
  await page.clock.install(); await page.goto(`${env.origin}/reset-password#token=${RESET_PROOF}`);
  await expect(page.getByTestId("password-auth-submit")).toBeEnabled();
  await page.getByLabel("New password", { exact: true }).fill(PASSWORD);
  await page.getByLabel("Confirm new password", { exact: true }).fill(PASSWORD);
  await page.getByTestId("password-auth-submit").click();
  await expect.poll(() => env.attempts("/api/v1/auth/password-resets")).toBe(1);
  await page.clock.fastForward(31000);
  await expect(page.getByRole("button", { name: "Try this account action again" })).toBeVisible();
  await expect(page.getByLabel("New password", { exact: true })).toHaveValue("");
  await expect(page.getByRole("button", { name: "Quick switch", exact: true })).toBeHidden();
  expect(env.attempts("/api/v1/auth/password-resets")).toBe(1);
});

test("the browser must return its session cookie before the workspace opens", async ({ page }) => {
  env.denyCookies();
  await page.goto(`${env.origin}/signin`);
  await page.getByLabel("Email address").fill(EMAIL_A);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByTestId("password-auth-submit").click();
  await expect(page.getByRole("button", { name: "Check connection again" })).toBeVisible();
  await expect(page.getByText(/Check that cookies are allowed/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Quick switch", exact: true })).toBeHidden();
  expect(env.fixture.count("/api/v1/auth/password-login")).toBe(1);
  expect(env.fixture.queryCount()).toBe(0);
});

test("session cookies survive reload and removing them locks the restored page", async ({ page, context }, info) => {
  await login(page); await page.reload();
  await expect(page.getByRole("button", { name: "Quick switch", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.screenshot({ path: info.outputPath("confirmed-session.png"), fullPage: true });
  const cookie = (await context.cookies()).find(value => value.name === "aqua-fixture");
  expect(cookie.httpOnly).toBe(true); expect(cookie.sameSite).toBe("Lax");
  await context.clearCookies();
  await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true })));
  await expect(page.getByLabel("Email address")).toBeVisible();
  expect(env.fixture.count("/api/v1/auth/password-login")).toBe(1);
  expect(env.fixture.queryCount()).toBe(0);
});

test("a different owner in cookie confirmation cannot adopt the login response", async ({ page }) => {
  const route = env.fixture.route.bind(env.fixture);
  env.fixture.route = (request, reply) => {
    if (new URL(request.url).pathname === "/api/auth/me" && env.fixture.email) env.fixture.email = EMAIL_B;
    return route(request, reply);
  };
  await page.goto(`${env.origin}/signin`);
  await page.getByLabel("Email address").fill(EMAIL_A);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByTestId("password-auth-submit").click();
  await expect(page.getByRole("button", { name: "Check connection again" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Quick switch", exact: true })).toBeHidden();
  expect(env.fixture.count("/api/v1/auth/password-login")).toBe(1);
  expect(env.fixture.queryCount()).toBe(0);
});
