// Optional extension of the existing immutable-assets P08 browser gate. It
// changes only the fixed fixture owner's presentation preference, never grants,
// providers, fake-job counts, traffic limits or production configuration.
export function visualPreferenceMode() {
  const mode = process.env.AQUA_P09_VISUAL_PREFERENCES ?? "";
  if (!["", "table"].includes(mode)) throw Error("p09_visual_preference_mode_invalid");
  return mode;
}

export async function prepareVisualPreference(ctx, mode) {
  if (mode !== "table") throw Error("p09_visual_preference_mode_invalid");
  ctx.stage = "prepare_saved_table_preference";
  const me = await ctx.rawRequest("GET", "/api/auth/me");
  if (me.status !== 200) throw Error("p09_visual_preference_session_invalid");
  const csrf = JSON.parse(me.body).csrf_token;
  if (typeof csrf !== "string" || csrf.length < 20 || csrf.length > 256) throw Error("p09_visual_preference_csrf_invalid");
  ctx.secrets.add(csrf);
  const read = await ctx.rawRequest("GET", "/api/v1/me/preferences");
  if (read.status !== 200) throw Error("p09_visual_preference_read_failed");
  const saved = JSON.parse(read.body);
  if (saved.schemaVersion !== 1 || !Number.isSafeInteger(saved.revision) || saved.revision < 1
    || saved.values?.initial_result_view !== "chart") throw Error("p09_visual_preference_fixture_default_invalid");
  const written = await ctx.rawRequest("PUT", "/api/v1/me/preferences", {
    schemaVersion: 1, expectedRevision: saved.revision, values: { ...saved.values, initial_result_view: "table" }
  }, csrf);
  if (written.status !== 200 || JSON.parse(written.body).values?.initial_result_view !== "table") {
    throw Error("p09_visual_preference_save_failed");
  }
  await ctx.navigate("/settings");
  await ctx.waitFor("Boolean(document.querySelector('#settings-field-accent'))&&!document.querySelector('#settings-field-accent').disabled", "p09_visual_preferences_reloaded");
  await ctx.click("[data-settings-category='charts']");
  await ctx.waitFor("document.querySelector('#settings-field-initial_result_view')?.value==='table'&&!document.querySelector('#settings-field-initial_result_view').disabled", "p09_saved_table_default_loaded");
  await ctx.check("saved Table preference reloads without opening a visual or starting analysis",
    "document.querySelector('#settings-field-initial_result_view').value==='table'&&!document.querySelector('.visual-pane,.visual-divider,.analysis-status')");
  await ctx.clickText("Back to workspace");
  await ctx.waitFor("location.pathname==='/'&&!document.querySelector('#settings-heading')&&Boolean(document.querySelector('.opal-composer textarea'))", "p09_visual_workspace_ready");
  ctx.results.push({ check: "following P08 explicit-chart checks run against the confirmed saved Table default", passed: true });
}
