export const EXPORT_SCENARIOS = Object.freeze(['password-export', 'google-export', 'lost-create', 'hash-interruption',
  'partial-download', 'digest-mismatch', 'foreign-probes', 'verification-failure']);
export const EXPORT_FILE = 'aqua-personal-data-v1.json';
export const EXPORT_MARKER = 'Synthetic private export project';
export function exportScenario(value) {
  if (!EXPORT_SCENARIOS.includes(value)) throw Error('export_scenario_invalid');
  return value;
}
export function exportFixtureBoundary(stats) {
  const value = stats?.export_fixture;
  if (!value || Object.keys(value).sort().join(',') !== 'body_exposed,downloads,real_provider_calls,starts' || stats?.actual_provider_calls !== 0 || stats?.fake_started !== 0 || stats?.physical_active !== 0
    || stats?.identity_fixture?.real_google_sdk_calls !== 0 || stats?.identity_fixture?.security_fake_jobs !== 0
    || value?.real_provider_calls !== 0 || value?.body_exposed !== false
    || !Number.isSafeInteger(value?.starts) || value.starts < 0 || value.starts > 4
    || !Number.isSafeInteger(value?.downloads) || value.downloads < 0 || value.downloads > 8) throw Error('export_provider_boundary_invalid');
  return true;
}
export function expectedExportActions(scenario) {
  exportScenario(scenario);
  return { proof_posts: 2, create_posts: scenario === 'verification-failure' ? 0 : 1,
    download_gets: scenario === 'verification-failure' ? 0 : scenario === 'foreign-probes' ? 2 : 1,
    local_transport_fault: ['partial-download', 'digest-mismatch'].includes(scenario) ? scenario : null };
}
