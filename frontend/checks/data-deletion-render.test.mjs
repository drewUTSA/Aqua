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
  if (url.pathname.endsWith('/PreferencesProvider.jsx')) source += '\nexport { Context as TestPreferencesContext };';
  if (url.pathname.endsWith('/DataDeletionProvider.jsx')) source += '\nexport { Context as TestDeletionContext };';
  const transformed = await transformWithEsbuild(source, url.pathname, { loader: 'jsx', format: 'esm' });
  let code = transformed.code.replace(/import\s+["'][^"']+\.css["'];?/g, '');
  const imports = new Map();
  for (const match of code.matchAll(/from\s+["']([^"']+)["']/g)) {
    const specifier = match[1]; imports.set(specifier, !specifier.startsWith('.') ? import.meta.resolve(specifier)
      : specifier.endsWith('.jsx') ? await jsxModule(new URL(specifier, url)) : new URL(specifier, url).href);
  }
  code = code.replace(/from\s+["']([^"']+)["']/g, (_, value) => `from ${JSON.stringify(imports.get(value))}`);
  const result = 'data:text/javascript;base64,' + Buffer.from(code).toString('base64'); compiled.set(url.href, result); return result;
}
const { default: PrivacyDeletions } = await import(await jsxModule(new URL('../src/settings/PrivacyDeletions.jsx', import.meta.url)));
const { default: DataDeletionProvider, TestDeletionContext } = await import(await jsxModule(new URL('../src/settings/DataDeletionProvider.jsx', import.meta.url)));
const { TestPreferencesContext } = await import(await jsxModule(new URL('../src/settings/PreferencesProvider.jsx', import.meta.url)));
const { default: SettingsInformation } = await import(await jsxModule(new URL('../src/settings/SettingsInformation.jsx', import.meta.url)));
const auth = { status: 'authenticated', demoMode: false, user: { id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa' }, csrfToken: 'synthetic-csrf', canQuery: false };
const preferences = { ready: true, loading: false, needsReload: false, capabilities: { private_data_delete: true },
  draft: { account: ACCOUNT_DEFAULTS, device: DEVICE_DEFAULTS }, effective: { account: ACCOUNT_DEFAULTS, device: DEVICE_DEFAULTS } };
const render = (Component, props = { auth }, overrides = {}, deletion = { open() {}, busy: false }) => renderToStaticMarkup(React.createElement(TestPreferencesContext.Provider,
  { value: { ...preferences, ...overrides } }, React.createElement(TestDeletionContext.Provider, { value: deletion }, React.createElement(Component, props))));
test('privacy deletion offers two explicit scoped reviews only under the existing server privacy capability', t => {
  const fetch = t.mock.method(globalThis, 'fetch', () => { throw Error('Unexpected network'); });
  const html = render(PrivacyDeletions);
  assert.match(html, /data-delete-private-history/); assert.match(html, /data-delete-private-account/);
  assert.doesNotMatch(html, /data-delete-private-(?:history|account)[^>]*disabled|<input|proof_token|receipt_token|synthetic-csrf/);
  for (const capabilities of [{}, { private_data_delete: false }, { account_delete: true, history_delete: true, recent_proof: true }]) {
    const blocked = render(PrivacyDeletions, { auth }, { capabilities });
    assert.match(blocked, /deletion is currently unavailable/); assert.doesNotMatch(blocked, /data-delete-private-history|data-delete-private-account/);
  }
  assert.equal(fetch.mock.calls.length, 0);
});
test('unresolved auth, unavailable preferences or an existing receipt cannot enable another deletion', () => {
  for (const overrides of [{ ready: false }, { loading: true }, { needsReload: true }]) assert.match(render(PrivacyDeletions, { auth }, overrides), /data-delete-private-history="true" disabled/);
  assert.match(render(PrivacyDeletions, { auth: { ...auth, status: 'loading' } }), /data-delete-private-account="true" disabled/);
  assert.match(render(PrivacyDeletions, { auth }, {}, { open() {}, busy: true }), /data-delete-private-account="true" disabled/);
  assert.match(render(PrivacyDeletions, { auth }, {}, null), /data-delete-private-account="true" disabled/);
  for (const value of [{ ...auth, demoMode: true }, { ...auth, user: null }]) assert.equal(render(PrivacyDeletions, { auth: value }), '<p>Sign in to review personal data deletion.</p>');
});
test('coordinator starts empty above the private subtree with no eager verification, deletion or reconciliation', t => {
  const fetch = t.mock.method(globalThis, 'fetch', () => { throw Error('Unexpected network'); });
  const html = renderToStaticMarkup(React.createElement(DataDeletionProvider, { auth }, ({ privateEpoch, privateBlocked }) => React.createElement('p', null, `${privateEpoch}:${privateBlocked}`)));
  assert.equal(html, '<p>0:false</p>'); assert.equal(fetch.mock.calls.length, 0);
});
test('only Privacy settings places the deletion entry point beside the existing private export panel', () => {
  const html = render(SettingsInformation, { category: 'privacy', auth });
  assert.match(html, /data-private-deletions/); assert.match(html, /data-private-exports/);
  assert.doesNotMatch(html, /Bulk history and account deletion remain unavailable/);
  for (const category of ['account', 'chat', 'workspace', 'region', 'accessibility', 'notifications']) assert.doesNotMatch(render(SettingsInformation, { category, auth }), /data-private-deletions/);
});
