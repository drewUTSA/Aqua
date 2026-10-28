import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";

export async function actualLifecycleWorkspace({ check, click, clickText, fill, waitFor, navigate, rawRequest, bridge, screenshot, csrf, recoverAnalysisRates, queryCount }) {
  const headers = { "X-CSRF-Token": csrf }, status = (id) => `/api/v1/analysis-requests/${id}`;
  const state = (value) => `document.querySelector('.analysis-status')?.dataset.analysisState===${JSON.stringify(value)}`;
  const stage = (value) => `document.querySelector('.analysis-status')?.dataset.analysisStage===${JSON.stringify(value)}`;
  const stats = async () => { const value = await bridge.send("workspace_stats"); assert.equal(value.actual_provider_calls, 0); assert.ok(value.maximum_physical_active <= 1); return value; };
  const saved = async (question) => {
    const rows = await rawRequest("GET", "/api/v1/chats"); assert.equal(rows.status, 200); const chat = JSON.parse(rows.body).items.find((item) => item.title === question); assert.ok(chat);
    const messages = await rawRequest("GET", `/api/v1/chats/${chat.id}/messages`); assert.equal(messages.status, 200);
    return { chat, id: JSON.parse(messages.body).items.at(-1).request_id };
  };
  const begin = async (question, atStage) => { await clickText("New chat"); await fill(".opal-composer textarea", question); await click("[aria-label='Send message']");
    await waitFor(stage(atStage), "actual_p07_held_stage", 10000); return saved(question); };
  const assertTerminal = async (id, expected) => { const result = await rawRequest("GET", status(id)); assert.equal(result.status, 200); const body = JSON.parse(result.body);
    assert.equal(body.request.state, expected); assert.equal(body.assistant_message.status, expected); return body; };

  await recoverAnalysisRates();
  const before = await stats(), generation = await begin("P07 fixture held generation", "generating");
  const queued = await rawRequest("POST", "/api/v1/chats", { client_request_id: randomUUID(), question: "P07 fixture queued cancel", model: "gemini" }, headers);
  assert.equal(queued.status, 202); const queuedBody = JSON.parse(queued.body); assert.equal(queuedBody.request.state, "queued");
  const queuedCancel = await rawRequest("POST", `${status(queuedBody.request.id)}/cancel`, {}, headers); assert.equal(queuedCancel.status, 200);
  await assertTerminal(queuedBody.request.id, "cancelled"); let measured = await stats(); assert.equal(measured.fake_started, before.fake_started + 1); assert.equal(measured.physical_active, 1);
  await check("actual queued cancellation commits terminal state without starting a second physical job", stage("generating"));
  await fill(".opal-composer textarea", "Actual unsent draft retained through cancellation"); await click("[aria-label='Cancel analysis']");
  await waitFor(state("cancelled"), "actual_generation_cancelled_after_child_reaped", 10000); await assertTerminal(generation.id, "cancelled");
  measured = await stats(); assert.equal(measured.physical_active, 0); assert.equal(measured.cancelled_executions, before.cancelled_executions + 1);
  await check("actual generation cancellation reaps server work and retains the newer unsent draft", "document.querySelector('.opal-composer textarea').value==='Actual unsent draft retained through cancellation'&&!document.querySelector('.conversation .sql-block')");
  await screenshot("p07-actual-server-cancelled-generation");

  await recoverAnalysisRates();
  const executionBefore = await stats(), execution = await begin("P07 fixture held execution", "executing");
  await click("[aria-label='Cancel analysis']"); await waitFor(state("cancelled"), "actual_execution_cancelled_after_reap", 10000); await assertTerminal(execution.id, "cancelled");
  measured = await stats(); assert.equal(measured.physical_active, 0); assert.equal(measured.fake_query_cancellations, executionBefore.fake_query_cancellations + 1);
  await check("actual execution cancellation is confirmed by the saved request and fake-query termination counter", "document.querySelector('.analysis-status').textContent.includes('cancelled on the server')&&!document.querySelector('.conversation .sql-block')");

  await recoverAnalysisRates();
  const reconnect = await begin("P07 fixture reconnect", "generating"), countBefore = queryCount(), startedBefore = (await stats()).fake_started;
  await navigate("/"); await waitFor("document.querySelector('.desktop-sidebar')?.textContent.includes('P07 fixture reconnect')", "actual_p07_recents_after_reload");
  await clickText("P07 fixture reconnect"); await waitFor(stage("generating"), "actual_p07_reconnected_by_saved_id", 10000);
  assert.equal(queryCount(), countBefore); assert.equal((await stats()).fake_started, startedBefore);
  await check("actual refresh reconnects to the canonical request using GET without resubmitting", "document.querySelectorAll('.conversation .message--user').length===1&&document.querySelectorAll('.conversation .message--aqua').length===1");
  await bridge.send("workspace_release"); await waitFor(state("complete"), "actual_p07_reconnect_result", 10000); await assertTerminal(reconnect.id, "complete");
  await fill(".opal-composer textarea", "P07 fixture follow-up"); await click("[aria-label='Send message']");
  await waitFor("document.querySelectorAll('.conversation .sql-block').length===2&&!document.querySelector('[aria-label=\"Cancel analysis\"]')", "actual_p07_follow_up_context", 10000);
  measured = await stats(); assert.ok(measured.last_context_turns >= 1 && measured.last_context_turns <= 8); assert.equal(measured.physical_active, 0);
  await check("actual follow-up uses bounded saved conversation context without a client transcript upload", "document.querySelector('.conversation').textContent.includes('Synthetic follow-up used its earlier saved question.')&&document.querySelectorAll('.conversation .message--user').length===2");
  await screenshot("p07-actual-reconnected-follow-up-history");

  await recoverAnalysisRates();
  const interrupted = await begin("P07 fixture held generation", "generating"); await bridge.send("workspace_restart");
  await waitFor(state("interrupted"), "actual_p07_restart_truthful_interruption", 10000); await assertTerminal(interrupted.id, "interrupted"); assert.equal((await stats()).physical_active, 0);
  await check("actual dispatcher restart leaves a saved interrupted request and no fabricated completed result", "!document.querySelector('.conversation .sql-block')&&document.querySelector('.analysis-status').textContent.includes('interrupted')");
  await clickText("New chat"); await fill(".opal-composer textarea", "P07 fixture queued cancel"); await click("[aria-label='Send message']");
  await waitFor(state("complete"), "actual_p07_dispatcher_recovered", 10000); assert.equal((await stats()).physical_active, 0);
  await check("actual restarted dispatcher accepts a new request after physical cleanup", "Boolean(document.querySelector('.conversation .sql-block'))");

  await recoverAnalysisRates();
  const deleted = await begin("P07 fixture held execution", "executing");
  await click(".desktop-sidebar .refined-chat-row:has([aria-current=page]) [aria-label^='Chat actions: ']");
  await clickText("Delete chat",'[role="menuitem"]'); await clickText("Delete chat",'dialog[open] button'); await waitFor("!document.querySelector('.workspace-editor,.conversation')", "actual_p07_pending_chat_deleted", 10000);
  const absent = await rawRequest("GET", status(deleted.id)); assert.equal(absent.status, 404);
  const stopBy = Date.now() + 8000; do { measured = await stats(); if (!measured.physical_active) break; await new Promise((resolve) => setTimeout(resolve, 60)); } while (Date.now() < stopBy);
  assert.equal(measured.physical_active, 0);
  await check("actual deletion cancels held work and prevents late saved-status resurrection", "!document.querySelector('.conversation,.sql-block,.analysis-status')");
  await recoverAnalysisRates();
  await fill(".opal-composer textarea", "P07 fixture exact precision"); await click("[aria-label='Send message']");
  await waitFor(state("complete"), "actual_p07_exact_metadata_result", 10000);
  await check("actual backend metadata preserves exact integer and decimal text with a plain precision note", "(()=>{const text=document.querySelector('.financial-table')?.textContent;return text?.includes('9007199254740993')&&text.includes('-0.1234567890123456789')&&document.querySelector('.result-metadata')?.textContent.includes('avoid rounding')&&!document.querySelector('.dashboard-preview,.kpi-grid')})()");
  await screenshot("p07-actual-exact-result-metadata"); assert.equal((await stats()).physical_active, 0);
}
