// Shared, bounded UI journeys over intercepted APIs. Actual database ownership,
// concurrency and restart checks remain independent backend/browser gates.
export async function workspaceJourneys({ check, click, clickText, fill, waitFor, evaluate, navigate, screenshot, fixture }) {
  const start = fixture.queryCount();
  await clickText("New chat"); await clickText("New chat");
  await check("New chat creates no empty server rows", `${fixture.queryCount() === start}`);
  await fill(".opal-composer textarea", "Unsent P06 starter draft"); await clickText("New chat");
  await clickText("Draft · New chat");
  await check("unsubmitted draft remains reachable after new-chat navigation", "document.querySelector('.opal-composer textarea').value==='Unsent P06 starter draft'");
  await fill(".opal-composer textarea", "");
  await clickText("New project"); await waitFor("Boolean(document.querySelector('.workspace-editor[open]'))", "new_project_dialog");
  await fill(".workspace-editor input:not([type=checkbox])", "Private P06 project"); await click(".workspace-editor button[type=submit]");
  await waitFor("!document.querySelector('.workspace-editor')&&document.querySelector('.desktop-sidebar').textContent.includes('Private P06 project')", "project_created");
  await clickText("Save a prompt"); await fill(".workspace-editor input:not([type=checkbox])", "Private P06 prompt");
  await fill(".workspace-editor textarea", "<img src=https://attacker.invalid/private onerror=alert(1)> literal saved draft");
  await click(".workspace-editor button[type=submit]");
  await waitFor("!document.querySelector('.workspace-editor')&&document.querySelector('.desktop-sidebar').textContent.includes('Private P06 prompt')", "prompt_created");
  await clickText("Private P06 prompt");
  await waitFor("document.querySelector('.opal-composer textarea').value.includes('literal saved draft')", "prompt_applied");
  await check("personal prompt application is literal and never submits analysis", `!document.querySelector('.opal-composer img[src*="attacker.invalid"]')&&window.__fixtureScriptExecuted===0&&${fixture.queryCount() === start}`);
  await click("[aria-label='Edit saved prompt Private P06 prompt']");
  await fill(".workspace-editor input:not([type=checkbox])", "Private P06 prompt renamed");
  await click(".workspace-editor input[type=checkbox]"); await click(".workspace-editor button[type=submit]");
  await waitFor("!document.querySelector('.workspace-editor')&&document.querySelector('.desktop-sidebar').textContent.includes('★ Private P06 prompt renamed')", "prompt_renamed_and_pinned");
  await check("saved prompt rename and pin are server confirmed", "document.querySelector('.desktop-sidebar').textContent.includes('★ Private P06 prompt renamed')");
  await fill(".opal-composer textarea", "P06 durable first question"); await click("[aria-label='Send message']");
  await waitFor("Boolean(document.querySelector('.conversation .message--aqua'))&&!document.querySelector('[aria-label=\"Stop response\"]')", "durable_first_answer");
  await fill(".opal-composer textarea", "P06 draft survives a saved-chat visit");
  await clickText("New chat"); await clickText("P06 durable first question");
  await waitFor("document.querySelector('.conversation')?.textContent.includes('P06 durable first question')", "owned_history_selected");
  await check("selecting saved history preserves its unsent draft", "document.querySelector('.opal-composer textarea').value==='P06 draft survives a saved-chat visit'");
  await navigate("/"); await waitFor("Boolean(document.querySelector('.opal-workspace:not([hidden])'))", "durable_refresh_login");
  await waitFor("document.querySelector('.desktop-sidebar').textContent.includes('P06 durable first question')", "recents_restored_after_reload");
  await clickText("P06 durable first question");
  await waitFor("document.querySelector('.conversation')?.textContent.includes('P06 durable first question')", "history_restored_after_reload");
  await check("reload restores submitted history but does not upload an old unsent draft", "document.querySelector('.opal-composer textarea').value===''&&Boolean(document.querySelector('.sql-block'))");
  await remapJourneys({ check, click, clickText, fill, waitFor, fixture });
  await clickText("P06 durable first question"); await waitFor("Boolean(document.querySelector('.sql-block'))", "original_chat_restored_after_remap_cases");
  await grantLossJourneys({ check, click, fill, waitFor, evaluate, fixture });
  await click("[aria-label='Edit chat P06 durable first question']");
  await fill(".workspace-editor input:not([type=checkbox])", "P06 renamed private chat");
  await evaluate("(()=>{const select=document.querySelector('.workspace-editor select');select.value=[...select.options].find(item=>item.textContent==='Private P06 project').value;select.dispatchEvent(new Event('change',{bubbles:true}));return true})()");
  await click(".workspace-editor button[type=submit]");
  await waitFor("!document.querySelector('.workspace-editor')&&document.querySelector('.desktop-sidebar').textContent.includes('P06 renamed private chat')", "chat_rename_membership_saved");
  await clickText("Private P06 project");
  await waitFor("Boolean(document.querySelector('.desktop-sidebar button[aria-current=page]'))", "project_membership_restored");
  await check("project grouping and recents select the same owned chat and canonical title", "document.querySelector('.conversation').textContent.includes('P06 durable first question')&&document.querySelector('.breadcrumb strong').textContent==='P06 renamed private chat'");
  await screenshot("p06-private-prompts-project-history");
  await evaluate("(()=>{const sidebar=document.querySelector('.desktop-sidebar .opal-sidebar__scroll');sidebar.scrollTop=sidebar.scrollHeight;return true})()");
  await screenshot("p06-private-project-recents-history");
  await evaluate("(()=>{document.querySelector('.desktop-sidebar .opal-sidebar__scroll').scrollTop=0;return true})()");
  await click("[aria-label='Edit chat P06 renamed private chat']"); await click(".workspace-editor input[type=checkbox]");
  await click(".workspace-editor button[type=submit]"); await waitFor("!document.querySelector('.workspace-editor')&&!document.querySelector('.desktop-sidebar button[aria-current=page]')", "chat_archived");
  await clickText("Show archived chats"); await waitFor("Boolean(document.querySelector('.desktop-sidebar button[aria-current=page]'))", "archived_chat_listed");
  await check("archived chats remain explicitly browsable", "document.querySelector('.desktop-sidebar').textContent.includes('P06 renamed private chat')");
  await click("[aria-label='Edit chat P06 renamed private chat']"); await clickText("Delete chat"); await clickText("Confirm delete");
  await waitFor("!document.querySelector('.workspace-editor')&&!document.querySelector('.conversation')", "chat_deleted");
  await clickText("Show active chats");
  await click("[aria-label='Edit project Private P06 project']"); await clickText("Delete project"); await clickText("Confirm delete");
  await waitFor("!document.querySelector('.workspace-editor')&&!document.querySelector('.desktop-sidebar').textContent.includes('Private P06 project')", "project_deleted");
  await check("chat deletion removes its readable history and result", "!document.querySelector('.conversation,.sql-block')");
  await clickText("All chats"); await fill(".opal-composer textarea", "");
}

async function remapJourneys({ check, click, clickText, fill, waitFor, fixture }) {
  const previousMessage = fixture.queryMessage; fixture.queryMessage = "Synthetic completed held result"; fixture.holdQuery = true;
  await clickText("New chat"); await fill(".opal-composer textarea", "Held first canonical draft case"); await click("[aria-label='Send message']");
  await waitFor("Boolean(document.querySelector('[aria-label=\"Stop response\"]'))", "first_remap_transport_held");
  await fill(".opal-composer textarea", "Original source unsent draft"); await clickText("Latest chats");
  await waitFor("Boolean(document.querySelector('.desktop-sidebar [aria-label=\"Edit chat Held first canonical draft case\"]'))", "completed_row_visible_before_response");
  await clickText("Held first canonical draft case"); await fill(".opal-composer textarea", "Canonical destination newer draft");
  fixture.holdQuery = false; await fixture.release("query");
  await waitFor("document.querySelector('.desktop-sidebar').textContent.includes('Recovered unsent draft')", "canonical_held_result_reconciled");
  await check("late first response preserves the independently opened canonical draft and source draft", "document.querySelector('.opal-composer textarea').value==='Canonical destination newer draft'&&document.querySelector('.desktop-sidebar').textContent.includes('Recovered unsent draft')");
  await click("[aria-label='Edit chat Held first canonical draft case']"); await clickText("Delete chat"); await clickText("Confirm delete");
  await waitFor("!document.querySelector('.workspace-editor')&&!document.querySelector('.conversation')", "first_remap_chat_removed");
  fixture.holdQuery = true; await fill(".opal-composer textarea", "Held first deleted canonical case"); await click("[aria-label='Send message']");
  await waitFor("Boolean(document.querySelector('[aria-label=\"Stop response\"]'))", "deleted_remap_transport_held");
  await fill(".opal-composer textarea", "Unsent text kept after canonical deletion"); await clickText("Latest chats");
  await waitFor("Boolean(document.querySelector('.desktop-sidebar [aria-label=\"Edit chat Held first deleted canonical case\"]'))", "deletable_canonical_row_visible");
  await clickText("Held first deleted canonical case");
  await click("[aria-label='Edit chat Held first deleted canonical case']"); await clickText("Delete chat"); await clickText("Confirm delete");
  await waitFor("!document.querySelector('.workspace-editor')&&!document.querySelector('.conversation')", "canonical_deleted_before_first_response");
  fixture.holdQuery = false; await fixture.release("query");
  await waitFor("document.querySelector('.desktop-sidebar').textContent.includes('Draft from deleted chat')", "late_deleted_response_fenced");
  await clickText("Draft · Draft from deleted chat");
  await check("confirmed deletion fences a held first response and preserves only its unsent text", "!document.querySelector('.conversation,.sql-block')&&document.querySelector('.opal-composer textarea').value==='Unsent text kept after canonical deletion'");
  fixture.queryMessage = previousMessage;
}

async function grantLossJourneys({ check, click, fill, waitFor, evaluate, fixture }) {
  const revalidate = () => evaluate("(()=>{const channel=new BroadcastChannel('aqua-session-events');channel.postMessage({type:'changed'});channel.close();return true})()");
  fixture.holdHistory = true; await clickTextVisible("Refresh saved chat");
  await waitFor("document.body.textContent.includes('Loading messages')", "authorized_history_read_held");
  await fill(".opal-composer textarea", "Draft kept after data grant loss");
  fixture.canQuery = false; await revalidate();
  await waitFor("Boolean(document.querySelector('.opal-workspace:not([hidden])'))&&document.querySelector('.opal-composer textarea').disabled", "history_grant_loss_confirmed");
  fixture.holdHistory = false; await fixture.release("history");
  await evaluate("new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve(true))))");
  await check("late authorized history cannot restore SQL after grant loss", "!document.querySelector('.sql-block')&&document.querySelector('.opal-composer textarea').value==='Draft kept after data grant loss'");
  fixture.canQuery = true; await revalidate();
  await waitFor("!document.querySelector('.opal-composer textarea').disabled", "history_grant_restored");
  await clickTextVisible("Refresh saved chat"); await waitFor("Boolean(document.querySelector('.sql-block'))", "granted_history_reloaded");
  const previousMessage = fixture.queryMessage; fixture.queryMessage = "GRANT_LOSS_SECRET_RESULT"; fixture.holdQuery = true;
  await fill(".opal-composer textarea", "Synthetic grant-race follow-up"); await click("[aria-label='Send message']");
  await waitFor("Boolean(document.querySelector('[aria-label=\"Stop response\"]'))", "authorized_submit_held");
  await fill(".opal-composer textarea", "Newer draft survives revoked request");
  fixture.canQuery = false; await revalidate();
  await waitFor("Boolean(document.querySelector('.opal-workspace:not([hidden])'))&&document.querySelector('.opal-composer textarea').disabled", "submit_grant_loss_confirmed");
  fixture.holdQuery = false; await fixture.release("query"); fixture.queryMessage = previousMessage;
  await evaluate("new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve(true))))");
  await check("late authorized submission cannot restore results after grant loss", "!document.querySelector('.sql-block')&&!document.body.textContent.includes('GRANT_LOSS_SECRET_RESULT')&&document.querySelector('.opal-composer textarea').value==='Newer draft survives revoked request'");
  fixture.canQuery = true; await revalidate();
  await waitFor("!document.querySelector('.opal-composer textarea').disabled", "submit_grant_restored");
  await clickTextVisible("Check saved request");
  await waitFor("document.querySelector('.conversation')?.textContent.includes('GRANT_LOSS_SECRET_RESULT')", "explicit_same_operation_recovered_after_grant_return");
  async function clickTextVisible(text) { await evaluate(`(()=>{const item=[...document.querySelectorAll('button')].find(item=>item.textContent.trim()===${JSON.stringify(text)}&&item.getClientRects().length&&!item.disabled);if(!item)throw Error('control_missing');item.click();return true})()`); }
}

export async function pendingWorkspaceJourney({ check, click, clickText, fill, waitFor, fixture }) {
  const count = fixture.queryCount();
  await check("other account cannot see the previous account's saved prompts", "!document.body.textContent.includes('Private P06 prompt renamed')");
  await clickText("Save a prompt"); await fill(".workspace-editor input:not([type=checkbox])", "Pending account private prompt");
  await fill(".workspace-editor textarea", "Draft for a later approved data request"); await click(".workspace-editor button[type=submit]");
  await waitFor("!document.querySelector('.workspace-editor')&&document.querySelector('.desktop-sidebar').textContent.includes('Pending account private prompt')", "pending_prompt_saved");
  await check("pending data access still permits private workspace CRUD without analysis", `${fixture.queryCount() === count}&&document.querySelector('.opal-composer textarea').disabled`);
  await click("[aria-label='Edit saved prompt Pending account private prompt']"); await clickText("Delete saved prompt"); await clickText("Confirm delete");
  await waitFor("!document.querySelector('.workspace-editor')&&!document.querySelector('.desktop-sidebar').textContent.includes('Pending account private prompt')", "pending_prompt_deleted");
}
