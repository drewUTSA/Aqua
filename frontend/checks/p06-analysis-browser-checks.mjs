import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { actualLifecycleWorkspace } from "./p07-real-browser-checks.mjs";

// Opt-in network-none fixture only. The production query service and storage
// routes run normally; the fixture supplies a fixed fake analytical result.
export async function actualAnalysisWorkspace({ check, click, clickText, fill, waitFor, evaluate, navigate, rawRequest, bridge, screenshot, csrf, recoverAnalysisRates, queryCount }) {
  const headers = { "X-CSRF-Token": csrf }, title = "Actual durable P06 synthetic question";
  const terminal = async (initial) => {
    let value = initial; const until = Date.now() + 10000;
    while (["queued", "running", "cancelling"].includes(value.request.state) && Date.now() < until) {
      await new Promise((resolve) => setTimeout(resolve, 50)); const reply = await rawRequest("GET", `/api/v1/analysis-requests/${value.request.id}`); assert.equal(reply.status, 200); value = JSON.parse(reply.body);
    }
    assert.ok(["complete", "error", "cancelled", "interrupted", "expired"].includes(value.request.state), "actual_request_terminal_deadline"); return value;
  };
  const revalidate = () => evaluate("(()=>{const channel=new BroadcastChannel('aqua-session-events');channel.postMessage({type:'changed'});channel.close();return true})()");
  await bridge.send("workspace_grant"); await revalidate();
  await waitFor("Boolean(document.querySelector('.opal-workspace:not([hidden])'))&&!document.querySelector('.opal-composer textarea').disabled", "actual_fake_data_grant_confirmed");
  await fill(".opal-composer textarea", title); await click("[aria-label='Send message']");
  await waitFor("Boolean(document.querySelector('.conversation .sql-block'))&&!document.querySelector('[aria-label=\"Stop response\"]')", "actual_durable_first_result");
  const chats = await rawRequest("GET", "/api/v1/chats"); assert.equal(chats.status, 200);
  const chat = JSON.parse(chats.body).items.find((item) => item.title === title); assert.ok(chat?.id); assert.equal(chat.message_count, 2);
  const firstPage = await rawRequest("GET", `/api/v1/chats/${chat.id}/messages`); assert.equal(firstPage.status, 200);
  const first = JSON.parse(firstPage.body).items; assert.deepEqual(first.map((item) => item.role), ["user", "aqua"]);
  assert.equal(first[1].reply_to, first[0].id); assert.equal(first[1].status, "complete"); assert.equal(first[1].response.status, "success");
  await navigate("/"); await waitFor(`document.querySelector('.desktop-sidebar')?.textContent.includes(${JSON.stringify(title)})`, "actual_durable_recents_after_reload");
  await clickText(title); await waitFor("Boolean(document.querySelector('.conversation .sql-block'))", "actual_saved_result_after_reload");
  await check("actual UI first submit restores canonical messages result and title after reload", `document.querySelectorAll('.conversation .message--user').length===1&&document.querySelectorAll('.conversation .message--aqua').length===1&&document.querySelector('.breadcrumb strong').textContent===${JSON.stringify(title)}`);
  await screenshot("p06-actual-restored-owned-history");
  const clientId = randomUUID(), input = { client_request_id: clientId, question: "Actual synthetic independent append", model: "gemini" };
  const appended = await rawRequest("POST", `/api/v1/chats/${chat.id}/messages`, input, headers); assert.equal(appended.status, 202);
  const canonical = await terminal(JSON.parse(appended.body));
  const replayed = await rawRequest("POST", `/api/v1/chats/${chat.id}/messages`, input, headers); assert.equal(replayed.status, 200);
  const replay = JSON.parse(replayed.body); assert.equal(replay.request.id, canonical.request.id);
  assert.equal(replay.input_message.id, canonical.input_message.id); assert.equal(replay.assistant_message.id, canonical.assistant_message.id);
  const forbiddenRetry = await rawRequest("POST", `/api/v1/chats/${chat.id}/messages/${first[0].id}/retries`, { client_request_id: randomUUID() }, headers);
  assert.equal(forbiddenRetry.status, 409, "completed_success_is_not_a_retryable_input");
  const finalPage = await rawRequest("GET", `/api/v1/chats/${chat.id}/messages`); assert.equal(finalPage.status, 200);
  const messages = JSON.parse(finalPage.body).items; assert.equal(messages.length, 4);
  assert.equal(messages.filter((item) => item.role === "user").length, 2); assert.deepEqual(messages.map((item) => item.sequence), [1, 2, 3, 4]);
  await navigate("/"); await waitFor(`document.querySelector('.desktop-sidebar')?.textContent.includes(${JSON.stringify(title)})`, "actual_retry_recents_reloaded");
  await clickText(title); await waitFor("document.querySelectorAll('.conversation .message--aqua').length===2", "actual_replayed_history_restored");
  await check("actual same-operation replay preserves canonical IDs and rejects retry of a successful input", "document.querySelectorAll('.conversation .message--user').length===2&&document.querySelectorAll('.conversation .sql-block').length===2");
  await recoverAnalysisRates();
  await fill(".opal-composer textarea", "P06 fixture transient failure"); await click("[aria-label='Send message']");
  await waitFor("Boolean([...document.querySelectorAll('.conversation button')].find(item=>item.textContent==='Try again'))&&!document.querySelector('[aria-label=\"Stop response\"]')", "actual_retryable_saved_failure");
  await clickText("Try again");
  await waitFor("document.querySelectorAll('.conversation .message--aqua').length===4&&document.querySelector('.analysis-status')?.dataset.analysisState==='complete'", "actual_ui_retry_saved", 10000);
  const afterRetry = await rawRequest("GET", `/api/v1/chats/${chat.id}/messages`); assert.equal(afterRetry.status, 200);
  const attempts = JSON.parse(afterRetry.body).items; assert.equal(attempts.length, 7); assert.equal(attempts.filter((item) => item.role === "user").length, 3);
  assert.equal(attempts.at(-1).reply_to, attempts.at(-3).id); assert.equal(attempts.at(-1).status, "complete");
  const retryBody = { client_request_id: randomUUID() }, retryPath = `/api/v1/chats/${chat.id}/messages/${attempts.at(-3).id}/retries`;
  const retried = await rawRequest("POST", retryPath, retryBody, headers); assert.equal(retried.status, 202);
  const retry = await terminal(JSON.parse(retried.body)); assert.equal(retry.input_message.id, attempts.at(-3).id);
  assert.equal(retry.assistant_message.reply_to, attempts.at(-3).id); assert.notEqual(retry.assistant_message.id, attempts.at(-1).id);
  const retryReplay = await rawRequest("POST", retryPath, retryBody, headers); assert.equal(retryReplay.status, 200);
  assert.equal(JSON.parse(retryReplay.body).assistant_message.id, retry.assistant_message.id);
  await navigate("/"); await waitFor(`document.querySelector('.desktop-sidebar')?.textContent.includes(${JSON.stringify(title)})`, "actual_retry_recents_reloaded");
  await clickText(title); await waitFor("document.querySelectorAll('.conversation .message--aqua').length===5", "actual_retry_history_restored");
  const stats = await bridge.send("workspace_stats"); assert.equal(stats.fake_executions, 5); assert.equal(stats.actual_provider_calls, 0);
  await check("actual Try again creates a saved assistant attempt for the original input without provider work", "document.querySelectorAll('.conversation .message--user').length===3&&document.querySelectorAll('.conversation .sql-block').length===4");
  await actualLifecycleWorkspace({ check, click, clickText, fill, waitFor, navigate, rawRequest, bridge, screenshot, csrf, recoverAnalysisRates, queryCount });
  await navigate("/"); await waitFor(`document.querySelector('.desktop-sidebar')?.textContent.includes(${JSON.stringify(title)})`, "actual_original_history_after_lifecycle");
  await clickText(title); await waitFor("document.querySelectorAll('.conversation .message--aqua').length===5", "actual_original_history_restored");
  await bridge.send("workspace_revoke"); await revalidate();
  await waitFor("Boolean(document.querySelector('.opal-workspace:not([hidden])'))&&document.querySelector('.opal-composer textarea').disabled&&!document.querySelector('.conversation .sql-block')", "actual_saved_data_revoked");
  const revokedPage = await rawRequest("GET", `/api/v1/chats/${chat.id}/messages`); assert.equal(revokedPage.status, 200);
  const revoked = JSON.parse(revokedPage.body).items;
  assert.equal(revoked.length, 8); assert.ok(revoked.filter((item) => item.role === "aqua").every((item) => item.response === null && item.content === "" && item.result_unavailable));
  assert.ok(revoked.filter((item) => item.role === "user").every((item) => item.response === null));
  await check("actual grant revocation withholds every saved result while keeping owned user messages", "!document.querySelector('.conversation .sql-block')&&document.querySelectorAll('.conversation .message--user').length===3");
  return chat.id;
}
