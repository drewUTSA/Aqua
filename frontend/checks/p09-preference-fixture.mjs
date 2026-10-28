// UI contract double only; actual authority/transactions use the separate DB gate.
import { ACCOUNT_DEFAULTS, clone, isRecord, validateValues } from '../src/settings/schema.js';

const capabilities = {
  account_security: false, notification_delivery: false, private_data_export: false,
  private_data_delete: false, personal_instructions: false, response_style: false,
  response_language: false, default_model: false, interface_languages: ['en']
};
export function preferenceFixture(fixture) {
  const accounts = new Map();
  return async ({ url, method, body, headers }, reply) => {
    if (url.pathname !== '/api/v1/me/preferences') return false;
    const respond = async (status, value = {}) => { await reply(status, value); return true; };
    if (!['GET', 'PUT'].includes(method)) return respond(405);
    if (!fixture.email || !fixture.session().user.id) return respond(401);
    if (url.search) return respond(422);
    const owner = fixture.session().user.id;
    const stored = accounts.get(owner) || { revision: 1, values: clone(ACCOUNT_DEFAULTS) };
    if (method === 'PUT') {
      if (headers.origin !== url.origin || headers['x-csrf-token'] !== 'fixture-session-csrf') return respond(403);
      if (!isRecord(body) || Object.keys(body).sort().join(',') !== 'expectedRevision,schemaVersion,values'
        || body.schemaVersion !== 1 || typeof body.schemaVersion !== 'number'
        || !Number.isSafeInteger(body.expectedRevision) || body.expectedRevision < 1) return respond(422);
      let values;
      try { values = validateValues(body.values, 'account'); } catch { return respond(422); }
      if (body.expectedRevision !== stored.revision) return respond(409);
      if (stored.revision >= Number.MAX_SAFE_INTEGER) return respond(409);
      accounts.set(owner, { revision: stored.revision + 1, values });
    }
    const current = accounts.get(owner) || stored;
    return respond(200, { schemaVersion: 1, revision: current.revision, values: clone(current.values), capabilities: clone(capabilities) });
  };
}
