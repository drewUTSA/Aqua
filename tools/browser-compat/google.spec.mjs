import { test, expect } from "@playwright/test";
import { setup } from "./fixture.mjs";

let env;
test.beforeEach(async ({ page, context }) => { env = null; env = await setup(page, context); env.fixture.redirectMode = true; });
test.afterEach(async () => { if (env) { await env.close(); expect(env.failures).toEqual([]); expect(env.external).toEqual([]); } });
const start = async page => {
  await page.goto(`${env.origin}/signin`);
  await expect(page.getByRole("button", { name: "Continue with Google", exact: true })).toBeVisible();
};

test("advertised redirect uses the exact callback and the production bridge confirms a cookie session", async ({ page }) => {
  await start(page);
  expect(await page.evaluate(() => ({ mode: window.__fixtureGoogleSettings.ux_mode, uri: window.__fixtureGoogleSettings.login_uri,
    nonce: window.__fixtureGoogleSettings.nonce, callback: typeof window.__fixtureGoogleSettings.callback }))).toEqual({
    mode: "redirect", uri: `${env.origin}/api/auth/google/redirect`, nonce: "fixture-google-nonce", callback: "undefined"
  });
  await page.getByRole("button", { name: "Continue with Google", exact: true }).click();
  await expect(page.getByRole("button", { name: "Quick switch", exact: true })).toBeVisible();
  await expect(page).toHaveURL(`${env.origin}/`);
  expect(env.attempts("/api/auth/google/redirect")).toBe(1);
  expect(env.attempts("/api/auth/google/redirect-state", "GET")).toBe(1);
  expect(env.attempts("/api/auth/google/redirect-complete")).toBe(1);
  expect(env.attempts("/api/auth/google")).toBe(0);
  expect(env.fixture.queryCount()).toBe(0);
});

test("missing provider cookie leaves a safe document and cannot create a session", async ({ page }) => {
  await page.addInitScript(() => { window.__fixtureOmitGoogleCookie = true; });
  await start(page); await page.getByRole("button", { name: "Continue with Google", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("could not confirm sign-in");
  await expect(page).toHaveURL(`${env.origin}/api/auth/google/redirect`);
  expect(await page.locator("script").count()).toBe(0);
  expect(await page.content()).not.toContain("fixture-google-credential");
  expect(env.attempts("/api/auth/google/redirect-complete")).toBe(0);
  expect(env.fixture.email).toBeNull();
});

test("provider failure never automatically repeats the completion POST", async ({ page }) => {
  env.fixture.redirectFailure = true;
  await start(page); await page.getByRole("button", { name: "Continue with Google", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("will not be retried automatically");
  await page.getByRole("link", { name: "Check your session", exact: true }).click();
  await expect(page.getByLabel("Email address")).toBeVisible();
  expect(env.attempts("/api/auth/google/redirect-complete")).toBe(1);
  expect(env.fixture.email).toBeNull();
});

test("a stalled redirect completion is bounded and keeps manual recovery", async ({ page }) => {
  env.blocked.add("/api/auth/google/redirect-complete");
  await page.clock.install(); await start(page);
  await page.getByRole("button", { name: "Continue with Google", exact: true }).click();
  await expect.poll(() => env.attempts("/api/auth/google/redirect-complete")).toBe(1);
  await page.clock.fastForward(31000);
  await expect(page.getByRole("status")).toContainText("could not confirm sign-in");
  await expect(page.getByRole("link", { name: "Check your session", exact: true })).toBeVisible();
  expect(env.attempts("/api/auth/google/redirect-complete")).toBe(1);
  expect(env.fixture.email).toBeNull();
});

test("the existing callback mode remains available while the feature is disabled", async ({ page }) => {
  env.fixture.redirectMode = false; await start(page);
  expect(await page.evaluate(() => typeof window.__fixtureGoogleSettings.callback)).toBe("function");
  await page.getByRole("button", { name: "Continue with Google", exact: true }).click();
  await expect(page.getByRole("button", { name: "Quick switch", exact: true })).toBeVisible();
  expect(env.attempts("/api/auth/google")).toBe(1);
  expect(env.attempts("/api/auth/google/redirect-complete")).toBe(0);
});
