import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import { webcrypto } from 'node:crypto';
import { EXPORT_SCENARIOS, exportScenario, exportFixtureBoundary, expectedExportActions, EXPORT_FILE } from './p11a-export-browser-contract.mjs';
import { EXPORT_FIXTURE_SCRIPT } from './p11a-export-browser-checks.mjs';
import { LIMITS } from './p08-browser-environment.mjs';

function fixture(body = '{"synthetic":"private fixture bytes"}', configure = () => {}) {
  const metrics = { fetches: 0, nativeClicks: 0, nativeRevokes: 0 };
  class FixtureURL extends URL {
    static createObjectURL() { return 'blob:synthetic-export-unit'; }
    static revokeObjectURL() { metrics.nativeRevokes++; }
  }
  class Anchor { click() { metrics.nativeClicks++; } }
  const source = new TextEncoder().encode(body);
  const sandbox = { URL: FixtureURL, HTMLAnchorElement: Anchor, Blob, Response, Uint8Array, TextDecoder, Promise, isSecureContext: true,
    crypto: { subtle: { digest: webcrypto.subtle.digest.bind(webcrypto.subtle) } },
    location: { href: 'https://aqua-browser.example.test/settings', origin: 'https://aqua-browser.example.test' },
    fetch: async () => { metrics.fetches++; return new Response(source, { headers: { 'Content-Type': 'application/json', 'Content-Length': String(source.length) } }); },
  };
  sandbox.window = sandbox;
  configure(sandbox);
  vm.runInNewContext(EXPORT_FIXTURE_SCRIPT, sandbox, { timeout: 1000 });
  return { sandbox, metrics, source };
}

test('export preload ignores off-origin and opaque documents before any native API read or mutation', () => {
  for(const origin of [null,undefined,'null','http://aqua-browser.example.test','https://aqua-browser.example.test.evil','https://aqua-browser.example.test:444','https://other.example.test']){
    const sandbox={location:{origin},isSecureContext:false};sandbox.window=sandbox;
    for(const key of ['crypto','fetch','URL','HTMLAnchorElement'])Object.defineProperty(sandbox,key,{configurable:true,get(){throw Error('off_origin_native_API_touched');}});
    const before=Object.getOwnPropertyDescriptors(sandbox);
    assert.doesNotThrow(()=>vm.runInNewContext(EXPORT_FIXTURE_SCRIPT,sandbox,{timeout:1000}));
    assert.deepEqual(Object.getOwnPropertyDescriptors(sandbox),before);
  }
});

test('export preload fails closed on the approved origin when SubtleCrypto or digest is missing', () => {
  for(const crypto of [undefined,null,{}, {subtle:null},{subtle:{}},{subtle:{digest:null}}]){
    assert.throws(()=>fixture(undefined,page=>{page.crypto=crypto;}),/export_fixture_secure_context_required/);
  }
});

test('export preload requires an actual secure context on the approved origin', () => {
  for(const secure of [false,undefined,null])assert.throws(()=>fixture(undefined,page=>{page.isSecureContext=secure;}),/export_fixture_secure_context_required/);
});

test('export preload fails closed when an approved-origin native interception API is missing', () => {
  for(const remove of [page=>{page.fetch=undefined;},page=>{page.URL=null;},page=>{page.URL.createObjectURL=undefined;},page=>{page.URL.revokeObjectURL=undefined;},page=>{page.HTMLAnchorElement.prototype.click=undefined;}]){
    assert.throws(()=>fixture(undefined,remove),/export_fixture_secure_context_required/);
  }
});

test('export browser matrix is closed and admits one creation with exact proof request counts', () => {
  assert.equal(EXPORT_SCENARIOS.length, 8);assert.equal(new Set(EXPORT_SCENARIOS).size, 8);
  for (const value of EXPORT_SCENARIOS) {
    assert.equal(exportScenario(value), value);const actions = expectedExportActions(value);
    assert.equal(actions.proof_posts, 2);assert.ok([0, 1].includes(actions.create_posts));assert.ok(actions.download_gets <= 2);
  }
  for (const value of ['expired-by-clock-change', '../other', 'password-export;id', '', null, {}]) assert.throws(() => exportScenario(value));
  assert.deepEqual(LIMITS, { milliseconds: 150000, requests: 250, api: 160, paused: 16, perSecond: 5, bodyBytes: 16384, fakeJobs: 12 });
});

test('export browser boundary rejects provider calls, exposed bodies and unbounded counters', () => {
  const valid = { actual_provider_calls: 0, fake_started: 0, physical_active: 0,
    identity_fixture: { real_google_sdk_calls: 0, security_fake_jobs: 0 },
    export_fixture: { real_provider_calls: 0, body_exposed: false, starts: 1, downloads: 1 } };
  assert.equal(exportFixtureBoundary(valid), true);
  for (const change of [v => v.actual_provider_calls++, v => v.fake_started++, v => v.physical_active++,
    v => v.identity_fixture.real_google_sdk_calls++, v => v.export_fixture.real_provider_calls++,
    v => v.export_fixture.body_exposed = true, v => v.export_fixture.raw_private_body = 'forbidden', v => v.export_fixture.starts = 5, v => v.export_fixture.downloads = 9,
    v => v.export_fixture.starts = -1, v => v.export_fixture.downloads = 0.5, v => delete v.export_fixture]) {
    const value = structuredClone(valid);change(value);assert.throws(() => exportFixtureBoundary(value));
  }
});

test('browser seam blocks OS saves and accepts only the fixed private Blob before revocation', () => {
  const { sandbox: page, metrics } = fixture();assert.equal(metrics.fetches, 0);
  const url = page.URL.createObjectURL(new Blob(['synthetic'], { type: 'application/json' }));
  const anchor = new page.HTMLAnchorElement();anchor.href = url;anchor.download = EXPORT_FILE;anchor.click();
  assert.equal(page.__exportMetrics.offered, 1);assert.equal(metrics.nativeClicks, 0);assert.equal(page.__exportBlobCount(), 1);
  page.URL.revokeObjectURL(url);assert.equal(page.__exportBlobCount(), 0);assert.equal(metrics.nativeRevokes, 1);
  assert.throws(() => anchor.click(), /unknown_export_blob/);anchor.download='unexpected.json';assert.throws(() => anchor.click(), /unknown_export_blob/);anchor.href='https://aqua-browser.example.test/file';assert.throws(() => anchor.click(), /unknown_export_blob/);
  assert.equal(metrics.nativeClicks, 0);
});

test('labeled local download faults preserve the real-request boundary and reject bodies above the old cap', async () => {
  const route = '/api/v1/me/data-exports/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/download';
  for (const fault of ['partial-download', 'digest-mismatch']) {
    const { sandbox: page, metrics, source } = fixture();page.__exportFault = fault;
    const result = new Uint8Array(await (await page.fetch(route)).arrayBuffer());
    assert.equal(metrics.fetches, 1);assert.equal(page.__exportMetrics.transport_faults, 1);
    if (fault === 'partial-download') assert.deepEqual(result, source.subarray(0, source.length - 1));
    else { assert.equal(result.length, source.length);assert.equal(result[0], source[0] ^ 1);assert.deepEqual(result.subarray(1), source.subarray(1)); }
    result.fill(0);assert.equal(page.__exportBlobCount(), 0);assert.equal(page.__exportMetrics.offered, 0);
  }
  const { sandbox: page } = fixture();page.__exportFault = 'unsupported';await assert.rejects(page.fetch(route), /export_fault_invalid/);
  const large = fixture('x'.repeat(16385));large.sandbox.__exportFault = 'partial-download';await assert.rejects(large.sandbox.fetch(route), /export_fault_body_bound/);
});

test('hash interruption seam holds a genuine native digest and releases no synthetic digest', async () => {
  const { sandbox: page } = fixture(), source = new Uint8Array([7, 8, 9]);
  const expected = new Uint8Array(await webcrypto.subtle.digest('SHA-256', source));
  page.__exportHoldHash = true;const pending = page.crypto.subtle.digest('SHA-256', source);
  for (let i = 0; i < 50 && !page.__exportReleaseHash; i++) await new Promise(resolve => setTimeout(resolve, 1));
  assert.equal(typeof page.__exportReleaseHash, 'function');assert.equal(page.__exportHeldBytes.buffer, source.buffer);
  source.fill(0);page.__exportReleaseHash();assert.deepEqual(new Uint8Array(await pending), expected);
  assert.equal(page.__exportReleaseHash, undefined);assert.ok(page.__exportHeldBytes.every(value => value === 0));
});
