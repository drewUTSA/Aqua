import test from 'node:test';
import assert from 'node:assert/strict';
import { makeFixture, EMAIL_A, EMAIL_B } from './p05-browser-fixture.mjs';
import { ACCOUNT_DEFAULTS } from '../src/settings/schema.js';

const origin = 'http://127.0.0.1:51437';
async function request(fixture, method = 'GET', body, extraHeaders = {}, query = '') {
  let response;
  await fixture.route({ url: origin + '/api/v1/me/preferences' + query, method,
    headers: { Origin: origin, 'X-CSRF-Token': 'fixture-session-csrf', ...extraHeaders },
    ...(body === undefined ? {} : { postData: JSON.stringify(body) }) }, (status, value) => { response = { status, value }; });
  return response;
}
const update = (revision = 1, values = ACCOUNT_DEFAULTS) => ({ schemaVersion: 1, expectedRevision: revision, values });

test('preference fixture needs authentication while analytical grants are independent', async () => {
  const fixture = makeFixture();
  assert.equal((await request(fixture)).status, 401);
  fixture.email = EMAIL_A; fixture.canQuery = false;
  const response = await request(fixture);
  assert.equal(response.status, 200); assert.deepEqual(response.value.values, ACCOUNT_DEFAULTS);
  assert.equal(response.value.capabilities.account_security, false);
  assert.deepEqual(response.value.capabilities.interface_languages, ['en']);
  assert.equal(fixture.canQuery, false);
});
test('preference fixture retains independent owner values and exact revision conflicts', async () => {
  const fixture = makeFixture(); fixture.email = EMAIL_A;
  assert.equal((await request(fixture, 'PUT', update(1, { ...ACCOUNT_DEFAULTS, accent: 'sage' }))).status, 200);
  assert.equal((await request(fixture, 'PUT', update())).status, 409);
  fixture.email = EMAIL_B;
  assert.equal((await request(fixture)).value.values.accent, 'pearl');
  assert.equal((await request(fixture, 'PUT', update(1, { ...ACCOUNT_DEFAULTS, accent: 'amber' }))).status, 200);
  fixture.email = EMAIL_A;
  const response = await request(fixture);
  assert.equal(response.value.values.accent, 'sage'); assert.equal(response.value.revision, 2);
});
test('preference fixture rejects missing CSRF and foreign origin without writes', async () => {
  const fixture = makeFixture(); fixture.email = EMAIL_A;
  assert.equal((await request(fixture, 'PUT', update(), { 'X-CSRF-Token': '' })).status, 403);
  assert.equal((await request(fixture, 'PUT', update(), { Origin: 'https://foreign.invalid' })).status, 403);
  assert.equal((await request(fixture)).value.revision, 1);
});
test('preference fixture atomically rejects protected, device and malformed full snapshots', async () => {
  const fixture = makeFixture(); fixture.email = EMAIL_A;
  for (const body of [
    { ...update(), owner_id: 'foreign' }, { ...update(), schemaVersion: true },
    { ...update(), expectedRevision: '1' }, update(1, { accent: 'sage' }),
    update(1, { ...ACCOUNT_DEFAULTS, can_query: true }), update(1, { ...ACCOUNT_DEFAULTS, motion: 'reduce' }),
    update(1, { ...ACCOUNT_DEFAULTS, precision: 2 }),
    update(1, JSON.parse(JSON.stringify(ACCOUNT_DEFAULTS).replace('"accent":"pearl"', '"accent":"pearl","__proto__":{}')))
  ]) assert.equal((await request(fixture, 'PUT', body)).status, 422);
  const response = await request(fixture);
  assert.equal(response.value.revision, 1); assert.deepEqual(response.value.values, ACCOUNT_DEFAULTS);
});
test('preference fixture rejects alternate methods and caller-owned query parameters', async () => {
  const fixture = makeFixture(); fixture.email = EMAIL_A;
  for (const method of ['POST', 'PATCH', 'DELETE']) assert.equal((await request(fixture, method)).status, 405);
  assert.equal((await request(fixture, 'GET', undefined, {}, '?owner_id=foreign')).status, 422);
});
