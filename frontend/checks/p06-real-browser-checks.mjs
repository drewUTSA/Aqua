import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { openPrompts, closePrompts, projectAction } from './homepage-browser-actions.mjs';

export async function actualPersonalWorkspace({ check, click, clickText, fill, waitFor, evaluate, navigate, rawRequest, screenshot, csrf }) {
  const headers = { "X-CSRF-Token": csrf };
  const ctx={check,click,clickText,fill,waitFor,evaluate};
  await openPrompts(ctx); await clickText("Save a prompt"); await fill(".workspace-editor input:not([type=checkbox])", "Actual private saved prompt");
  await fill(".workspace-editor textarea", "<img src=https://attacker.invalid/personal onerror=alert(1)> literal private prompt");
  await click(".workspace-editor button[type=submit]");
  await waitFor("!document.querySelector('.workspace-editor')&&document.querySelector('[aria-label=\"Private saved prompts\"]').textContent.includes('Actual private saved prompt')", "actual_prompt_saved");
  await navigate("/"); await waitFor("Boolean(document.querySelector('.opal-workspace'))", 'actual_prompt_workspace_reloaded'); await openPrompts(ctx);
  await waitFor("document.querySelector('[aria-label=\"Private saved prompts\"]')?.textContent.includes('Actual private saved prompt')", "actual_prompt_survives_reload");
  await check("actual no-dataset account restores its private saved prompt after reload", "document.querySelector('.opal-composer textarea').disabled&&!document.querySelector('img[src*=\"attacker.invalid\"]')");
  const first = await rawRequest("GET", "/api/v1/me/saved-prompts"); assert.equal(first.status, 200);
  const saved = JSON.parse(first.body).items.find((item) => item.label === "Actual private saved prompt"); assert.ok(saved?.id);
  // Twenty additional small rows exercise the real keyset controls with bounded
  // writes inside the existing 60/account/minute workspace admission budget.
  for (let index = 0; index < 20; index++) {
    const created = await rawRequest("POST", "/api/v1/me/saved-prompts", { client_request_id: randomUUID(), label: `Paged prompt ${index}`, prompt: `Synthetic private prompt ${index}` }, headers);
    assert.equal(created.status, 201, "bounded_prompt_page_setup");
  }
  const page = await rawRequest("GET", "/api/v1/me/saved-prompts");
  const cursor = JSON.parse(page.body).next_cursor; assert.equal(typeof cursor, "string");
  await navigate("/"); await waitFor("Boolean(document.querySelector('.opal-workspace'))", 'actual_paged_workspace_reloaded'); await openPrompts(ctx);
  await waitFor("Boolean([...document.querySelectorAll('[aria-label=\"Private saved prompts\"] button')].find(item=>item.textContent==='More saved prompts'))", "actual_prompt_cursor_available");
  await clickText("More saved prompts"); await waitFor("document.querySelector('[aria-label=\"Private saved prompts\"]').textContent.includes('Actual private saved prompt')", "actual_older_prompt_page");
  await clickText("First saved prompts"); await waitFor("!document.querySelector('[aria-label=\"Private saved prompts\"]').textContent.includes('Actual private saved prompt')", "actual_first_prompt_page_returned");
  const tampered = await rawRequest("GET", `/api/v1/me/saved-prompts?cursor=${encodeURIComponent(cursor + "x")}`);
  assert.equal(tampered.status, 422, "tampered_personal_cursor_rejected");
  await check("actual private prompts use bounded keyset pages and reject cursor tampering", "!document.querySelector('[aria-label=\"Private saved prompts\"]').textContent.includes('Actual private saved prompt')");
  await closePrompts(ctx);
  const forged = await rawRequest("POST", "/api/v1/projects", { client_request_id: randomUUID(), name: "Forbidden owner project", owner_id: randomUUID() }, headers);
  assert.equal(forged.status, 422, "workspace_mass_assignment_rejected");
  const missingCsrf = await rawRequest("POST", "/api/v1/projects", { client_request_id: randomUUID(), name: "No CSRF project" });
  assert.equal(missingCsrf.status, 403, "workspace_mutation_requires_csrf");
  const after = await rawRequest("GET", "/api/v1/projects"); assert.equal(after.status, 200); assert.deepEqual(JSON.parse(after.body).items, []);
  await check("actual workspace rejects forged ownership and missing CSRF without creating rows", "!document.body.textContent.includes('Forbidden owner project')&&!document.body.textContent.includes('No CSRF project')");
  const search = await rawRequest("POST", "/api/v1/chats/search", { search: "Synthetic private title prefix", limit: 20, archived: false }, headers);
  assert.equal(search.status, 200); assert.deepEqual(JSON.parse(search.body).items, []);
  const noSearchCsrf = await rawRequest("POST", "/api/v1/chats/search", { search: "Synthetic private title prefix" });
  assert.equal(noSearchCsrf.status, 403, "private_title_search_requires_csrf");
  await check("actual private title search uses a protected JSON body without dataset access", "document.querySelector('.opal-composer textarea').disabled");
  await click("[aria-label='New project']"); await fill(".workspace-editor input:not([type=checkbox])", "Actual private project");
  await click(".workspace-editor button[type=submit]");
  await waitFor("!document.querySelector('.workspace-editor')&&document.querySelector('.desktop-sidebar').textContent.includes('Actual private project')", "actual_project_saved");
  await projectAction(ctx, 'Actual private project', 'Rename project'); await fill(".workspace-editor input:not([type=checkbox])", "Actual renamed project");
  await click(".workspace-editor button[type=submit]");
  await waitFor("!document.querySelector('.workspace-editor')&&document.querySelector('.desktop-sidebar').textContent.includes('Actual renamed project')", "actual_project_renamed");
  await evaluate("(()=>{const sidebar=document.querySelector('.desktop-sidebar .opal-sidebar__scroll');sidebar.scrollTop=sidebar.scrollHeight;return true})()");
  await screenshot("p06-actual-private-project-prompts");
  await evaluate("(()=>{document.querySelector('.desktop-sidebar .opal-sidebar__scroll').scrollTop=0;return true})()");
  await projectAction(ctx, 'Actual renamed project', 'Delete project'); await clickText('Delete project', 'dialog[open] button');
  await waitFor("!document.querySelector('.workspace-editor')&&!document.querySelector('.desktop-sidebar').textContent.includes('Actual renamed project')", "actual_project_deleted");
  await check("actual private project create rename and deletion complete without dataset access", "document.querySelector('.opal-composer textarea').disabled");
  return { promptId: saved.id, cursor };
}
export async function foreignPersonalWorkspace({ check, rawRequest, workspace, csrf }) {
  const { promptId, cursor, chatId } = workspace;
  const listed = await rawRequest("GET", "/api/v1/me/saved-prompts"); assert.equal(listed.status, 200);
  assert.equal(JSON.parse(listed.body).items.some((item) => item.id === promptId), false);
  const changed = await rawRequest("PATCH", `/api/v1/me/saved-prompts/${promptId}`, { revision: 1, label: "Forged rename" }, { "X-CSRF-Token": csrf });
  assert.equal(changed.status, 404, "foreign_saved_prompt_is_unavailable");
  const foreignCursor = await rawRequest("GET", `/api/v1/me/saved-prompts?cursor=${encodeURIComponent(cursor)}`);
  assert.equal(foreignCursor.status, 422, "personal_cursor_bound_to_account");
  if (chatId) {
    const messages = await rawRequest("GET", `/api/v1/chats/${chatId}/messages`); assert.equal(messages.status, 404, "foreign_chat_history_is_unavailable");
    const rename = await rawRequest("PATCH", `/api/v1/chats/${chatId}`, { revision: 1, title: "Forbidden foreign chat title" }, { "X-CSRF-Token": csrf });
    assert.equal(rename.status, 404, "foreign_chat_cannot_be_renamed");
  }
  await check("actual second account cannot list or change the first account's private prompt", "!document.body.textContent.includes('Actual private saved prompt')");
}
