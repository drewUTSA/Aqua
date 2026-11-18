import assert from "node:assert/strict";

export const RESULT_CASES = [
  { question: "P08 chart primitives", count: "Among the 3 returned rows, 1 saved value is missing in this field. 2 have a value.", values: ["-12.5", "0"] },
  { question: "P08 chart exact values", count: "Among the 2 returned rows, 0 saved values are missing in this field. 2 have a value.", values: ["-0.1234567890123456789", "9007199254740993"] },
];
const endpoint = "/api/v1/companion/result-brief";

async function durableCounts(ctx, label, expected) {
  ctx.stage = label;
  const stats = await ctx.bridge.send("workspace_stats");
  const observed = {
    jobs: stats.result_brief_jobs, messages: stats.result_brief_messages,
    started: stats.fake_started, executed: stats.fake_executions, providers: stats.actual_provider_calls,
  };
  assert.deepEqual(observed, { jobs: expected, messages: expected * 2, started: expected, executed: expected, providers: 0 });
  ctx.results.push({ check: label, passed: true });
  return { stage: label, ...observed };
}

async function inspectField(ctx, item, index) {
  await ctx.evaluate(`document.querySelectorAll('.conversation [data-understand-result]')[${index}].click();true`);
  await ctx.waitFor("Boolean(document.querySelector('[data-result-facts]'))", "initial_saved_field_ready");
  await ctx.check("The companion shows the original saved question", `document.querySelector('.result-companion__question').textContent===${JSON.stringify(item.question)}`);
  await ctx.evaluate("(()=>{const select=document.querySelector('[data-result-column]');select.value='1';select.dispatchEvent(new Event('change',{bubbles:true}));return true})()");
  const values = "Array.from(document.querySelectorAll('.result-companion__value code'),el=>el.textContent)";
  await ctx.waitFor(`(${values}).length===2`, "numeric_saved_field_ready");
  const expected = JSON.stringify(item.values);
  await ctx.check("Both saved extrema retain exact display precision", `JSON.stringify(${values})===${JSON.stringify(expected)}`);
  await ctx.check("Returned and missing values have the expected counts", `document.querySelector('[data-result-facts] > p').textContent===${JSON.stringify(item.count)}`);
  const references = item.values.map((value, idx) => `Saved row ${2 - idx}, field 2 (measure): ${value}`);
  await ctx.check("Extrema link to the original saved order", `JSON.stringify(Array.from(document.querySelectorAll('.result-companion__witnesses li'),el=>el.textContent))===${JSON.stringify(JSON.stringify(references))}`);
  await ctx.screenshot(index ? "saved-result-exact-values" : "saved-result-missing-value");
  await ctx.click("[data-close-result-companion]");
  await ctx.waitFor("!document.querySelector('[data-result-companion]')", "saved_companion_closed");
}

export async function savedResultBrief(ctx, submit) {
  const samples = [];
  const shell = process.env.AQUA_P05_EXPECTED_SHELL || "opal";
  await ctx.check("The requested workspace shell is active", `document.querySelector('.opal-workspace').dataset.uiShell===${JSON.stringify(shell)}`);
  samples.push(await durableCounts(ctx, "Empty saved workspace", 0));
  await submit(RESULT_CASES[0].question);
  samples.push(await durableCounts(ctx, "First explicit analysis saved", 1));
  await inspectField(ctx, RESULT_CASES[0], 0);
  samples.push(await durableCounts(ctx, "Reading missing values preserves saved work", 1));
  await submit(RESULT_CASES[1].question);
  samples.push(await durableCounts(ctx, "Second explicit analysis saved", 2));
  const title = RESULT_CASES[0].question;
  await ctx.navigate("/");
  await ctx.waitFor(`Array.from(document.querySelectorAll('.desktop-sidebar button')).some(el=>el.textContent.trim()===${JSON.stringify(title)})`, "saved_history_loaded");
  await ctx.clickText(title, ".desktop-sidebar button");
  await ctx.waitFor("document.querySelectorAll('.conversation [data-understand-result]').length===2", "saved_results_rehydrated");
  await inspectField(ctx, RESULT_CASES[1], 1);
  ctx.stage = "owned_result_binding_and_csrf";
  const me = await ctx.rawRequest("GET", "/api/auth/me");
  const chats = await ctx.rawRequest("GET", "/api/v1/chats");
  assert.equal(me.status, 200); assert.equal(chats.status, 200);
  const session = JSON.parse(me.body), chat = JSON.parse(chats.body).items.find(item => item.title === title);
  assert.equal(chat?.message_count, 4);
  const messages = await ctx.rawRequest("GET", `/api/v1/chats/${chat.id}/messages`);
  assert.equal(messages.status, 200);
  const answer = JSON.parse(messages.body).items.at(-1);
  assert.equal(answer.role, "aqua"); assert.equal(answer.status, "complete"); assert.ok(answer.request_id);
  const body = { schemaVersion: 1, request_id: answer.request_id, column_index: 1 };
  const accepted = await ctx.rawRequest("POST", endpoint, body, session.csrf_token);
  assert.equal(accepted.status, 200);
  const envelope = JSON.parse(accepted.body);
  assert.equal(envelope.chat_id, chat.id); assert.equal(envelope.request_id, answer.request_id);
  assert.equal(envelope.owner_id, session.user.id); assert.equal(envelope.assistant_message_id, answer.id);
  const csrf = await ctx.rawRequest("POST", endpoint, body);
  assert.equal(csrf.status, 403); assert.equal(Object.hasOwn(JSON.parse(csrf.body), "brief"), false);
  ctx.results.push({ check: "Saved reply matches its authenticated owner, chat, request and message; missing CSRF is denied", passed: true });
  samples.push(await durableCounts(ctx, "Repeated field reads preserve saved work", 2));
  await ctx.bridge.send("workspace_revoke"); await ctx.navigate("/");
  await ctx.waitFor("document.querySelector('.opal-composer textarea')?.disabled===true", "dataset_access_revoked");
  const denied = await ctx.rawRequest("POST", endpoint, body, session.csrf_token);
  ctx.stage = "revoked_result_boundary";
  assert.equal(denied.status, 403); assert.equal(Object.hasOwn(JSON.parse(denied.body), "brief"), false);
  await ctx.check("A revoked grant prevents opening the saved field", "!document.querySelector('[data-understand-result],[data-result-facts]')");
  samples.push(await durableCounts(ctx, "Revocation preserves saved work", 2));
  // Unmount the reopened workspace and its canvas before the separately timed
  // process-close assertion. BrowserPipe still requires Chrome to exit normally.
  ctx.navigating = true;
  try {
    await ctx.cdp.send("Page.navigate", { url: "about:blank" });
    await ctx.waitFor("location.href==='about:blank'&&document.readyState==='complete'", "saved_result_workspace_unloaded");
  } finally { ctx.navigating = false; }
  return { samples, csrf_denial: csrf.status, revoked_grant: denied.status, answers_inspected: RESULT_CASES.length };
}
