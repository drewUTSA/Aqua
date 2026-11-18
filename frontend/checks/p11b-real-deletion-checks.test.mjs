import assert from 'node:assert/strict';
import test from 'node:test';
import { confirmedDeletionSchema } from './p11b-real-deletion-checks.mjs';

test('deletion evidence binds both bridge observations to the current schema and independent authority', () => {
  const ready = { schema_version: 10, identity_fixture: { actual_independent_authority: true } };
  const terminal = { status: 'passed', schema_version: 10, actual_independent_authority: true };
  assert.equal(confirmedDeletionSchema(ready, terminal), 10);
  for (const schema of [9, 11, true, '10', null, undefined]) {
    assert.throws(() => confirmedDeletionSchema({ ...ready, schema_version: schema }, terminal));
    assert.throws(() => confirmedDeletionSchema(ready, { ...terminal, schema_version: schema }));
    assert.throws(() => confirmedDeletionSchema({ ...ready, schema_version: schema }, { ...terminal, schema_version: schema }));
  }
  for (const authority of [false, null, undefined, 1]) {
    assert.throws(() => confirmedDeletionSchema({ ...ready, identity_fixture: { actual_independent_authority: authority } }, terminal));
    assert.throws(() => confirmedDeletionSchema(ready, { ...terminal, actual_independent_authority: authority }));
  }
  assert.throws(() => confirmedDeletionSchema(null, terminal));
  assert.throws(() => confirmedDeletionSchema(ready, null));
  assert.throws(() => confirmedDeletionSchema(ready, { ...terminal, status: 'failed' }));
});
