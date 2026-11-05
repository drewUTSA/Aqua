import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { readFile } from 'node:fs/promises';
import { transformWithEsbuild } from 'vite';
import { ACCOUNT_DEFAULTS, DEVICE_DEFAULTS } from '../src/settings/schema.js';

const compiled = new Map();
async function jsxModule(url) {
  if (compiled.has(url.href)) return compiled.get(url.href);
  let source = await readFile(url, 'utf8');
  // Expose the real provider's context in this offline module only. No product
  // hook, state initializer, endpoint or capability is replaced by this seam.
  if (url.pathname.endsWith('/PreferencesProvider.jsx')) source += '\nexport { Context as TestPreferencesContext };';
  const transformed = await transformWithEsbuild(source, url.pathname, { loader: 'jsx', format: 'esm' });
  let code = transformed.code.replace(/import\s+["'][^"']+\.css["'];?/g, '');
  const imports = new Map();
  for (const match of code.matchAll(/from\s+["']([^"']+)["']/g)) {
    const specifier = match[1];
    imports.set(specifier, !specifier.startsWith('.') ? import.meta.resolve(specifier)
      : specifier.endsWith('.jsx') ? await jsxModule(new URL(specifier, url)) : new URL(specifier, url).href);
  }
  code = code.replace(/from\s+["']([^"']+)["']/g, (_, specifier) => `from ${JSON.stringify(imports.get(specifier))}`);
  const result = 'data:text/javascript;base64,' + Buffer.from(code).toString('base64');
  compiled.set(url.href, result);
  return result;
}
const { default: PrivacyExports } = await import(await jsxModule(new URL('../src/settings/PrivacyExports.jsx', import.meta.url)));
const { default: ExportReviewDialog } = await import(await jsxModule(new URL('../src/settings/ExportReviewDialog.jsx', import.meta.url)));
const { default: SettingsInformation } = await import(await jsxModule(new URL('../src/settings/SettingsInformation.jsx', import.meta.url)));
const { TestPreferencesContext } = await import(await jsxModule(new URL('../src/settings/PreferencesProvider.jsx', import.meta.url)));
const owner = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const auth = { demoMode: false, status: 'authenticated', user: { id: owner }, csrfToken: 'synthetic-csrf', canQuery: false };
const preferences = cap => ({ ready: true, loading: false, needsReload: false,
  capabilities: { private_data_export: cap }, draft: { account: ACCOUNT_DEFAULTS, device: DEVICE_DEFAULTS },
  effective: { account: ACCOUNT_DEFAULTS, device: DEVICE_DEFAULTS } });
const render = (Component, props, cap = true) => renderToStaticMarkup(React.createElement(TestPreferencesContext.Provider,
  { value: preferences(cap) }, React.createElement(Component, props)));

test('private export panel performs no eager reads and uses only the server privacy capability', t => {
  const fetch = t.mock.method(globalThis, 'fetch', () => { throw Error('Unexpected network request'); });
  const enabled = render(PrivacyExports, { auth });
  assert.match(enabled, /data-start-private-export/);
  assert.match(enabled, /data-review-private-exports/);
  assert.doesNotMatch(enabled, /data-start-private-export[^>]*disabled|data-review-private-exports[^>]*disabled/);
  assert.doesNotMatch(enabled, /data-save-private-export|data-download-private-export|blob:|aqua-personal-data-v1\.json|<input/);
  const disabled = render(PrivacyExports, { auth }, false);
  assert.match(disabled, /Private exports are currently unavailable/);
  assert.doesNotMatch(disabled, /data-start-private-export|data-review-private-exports/);
  assert.equal(fetch.mock.calls.length, 0);
});

test('demo, absent owner and unresolved sign-in cannot offer private exports', t => {
  const fetch = t.mock.method(globalThis, 'fetch', () => { throw Error('Unexpected network request'); });
  for (const value of [{ ...auth, demoMode: true }, { ...auth, user: null }]) {
    assert.equal(render(PrivacyExports, { auth: value }), '<p>Sign in to review personal exports.</p>');
  }
  const unresolved = render(PrivacyExports, { auth: { ...auth, status: 'refreshing' } });
  assert.match(unresolved, /data-start-private-export="true" disabled/);
  assert.match(unresolved, /data-review-private-exports="true" disabled/);
  assert.equal(fetch.mock.calls.length, 0);
});

test('export dialog starts with a scope review and cannot silently verify, queue or download', t => {
  const fetch = t.mock.method(globalThis, 'fetch', () => { throw Error('Unexpected network request'); });
  const html = render(ExportReviewDialog, { auth, allowed: true, methods: {}, onClose() {}, onJob() {}, onUncertain() {} });
  assert.match(html, /data-export-dialog-phase="review"/);
  assert.match(html, /Continue to verification/);
  assert.match(html, /temporary export expires one hour/);
  assert.doesNotMatch(html, /<input|data-create-private-export|data-account-start-google|data-save-private-export|proof_token|synthetic-csrf/);
  assert.equal(fetch.mock.calls.length, 0);
});

test('the privacy settings section owns the export entry point without adding account capabilities', t => {
  const fetch = t.mock.method(globalThis, 'fetch', () => { throw Error('Unexpected network request'); });
  assert.match(render(SettingsInformation, { category: 'privacy', auth }), /data-private-exports/);
  for (const category of ['chat', 'workspace', 'appearance', 'region', 'accessibility', 'account', 'notifications']) {
    assert.doesNotMatch(render(SettingsInformation, { category, auth }), /data-private-exports|data-start-private-export/);
  }
  assert.equal(fetch.mock.calls.length, 0);
});
