// Real UI navigation helpers. These never dispatch private APIs or change state
// behind a component; each action follows its visible, named control.
const visible = "el=>el.getClientRects().length&&!el.closest('[hidden],[inert]')";
const q = JSON.stringify;
export async function ensureNavigation({ evaluate, click, waitFor }) {
  if (!await evaluate(`Boolean([...document.querySelectorAll('.opal-account [aria-label="Account menu"]')].find(${visible}))`)) {
    await click('[aria-label="Open navigation"]');
    await waitFor(`Boolean([...document.querySelectorAll('.opal-account [aria-label="Account menu"]')].find(${visible}))`, 'single_navigation_entry_ready');
  }
}
export async function openAccount(ctx) {
  await ensureNavigation(ctx);
  await ctx.click('.opal-account [aria-label="Account menu"]');
  await ctx.waitFor('Boolean(document.querySelector(\'[role="menu"][aria-label="Your account"]\'))', 'single_account_menu_ready');
}
export async function accountAction(ctx, action) {
  await openAccount(ctx);
  await ctx.evaluate(`(()=>{const el=[...document.querySelectorAll('[role="menuitem"]')].find(el=>{if(!(${visible})(el))return false;const copy=el.cloneNode(true);copy.querySelectorAll('[aria-hidden="true"]').forEach(node=>node.remove());return copy.textContent.trim()===${q(action)}});if(!el||el.disabled)throw Error('account_action_missing');el.click();return true})()`);
  if(action==='Settings')await ctx.waitFor('Boolean(document.querySelector("#settings-heading"))','account_settings_ready');
  if (action === 'Sign out') {
    await ctx.waitFor('Boolean([...document.querySelectorAll("dialog[open]")].find(el=>el.textContent.includes("Sign out of AQUA?")))', 'logout_confirmation_ready');
    await ctx.clickText('Sign out', 'dialog[open] button');
  }
}
export async function recentsAction(ctx, action) {
  await ensureNavigation(ctx); await ctx.click('[aria-label="Recents actions"]');
  await ctx.clickText(action, '[role="menuitem"]');
}
export async function openDrafts(ctx) {
  await ensureNavigation(ctx); await ctx.click('[aria-label="Recents actions"]');
  await ctx.evaluate(`(()=>{const el=[...document.querySelectorAll('[role="menuitem"]')].find(el=>(${visible})(el)&&/^Unsent drafts [(][0-9]+[)]$/.test(el.textContent.trim()));if(!el||el.disabled)throw Error('draft_entry_missing');el.click();return true})()`);
  await ctx.waitFor('Boolean([...document.querySelectorAll("dialog[open]")].find(el=>el.textContent.includes("Unsent drafts")))', 'unsent_drafts_dialog_ready');
}
export async function chatAction(ctx, title, action) {
  await ensureNavigation(ctx); await ctx.click(`[aria-label=${q('Chat actions: '+title)}]`);
  await ctx.clickText(action, '[role="menuitem"]');
}
export async function projectAction(ctx, name, action) {
  await ensureNavigation(ctx); await ctx.click(`[aria-label=${q('Project actions: '+name)}]`);
  await ctx.clickText(action, '[role="menuitem"]');
}
export async function startBlankChat(ctx) {
  await ensureNavigation(ctx);
  const exists = await ctx.evaluate(`Boolean([...document.querySelectorAll('[aria-label="New chat"],.new-chat')].find(${visible}))`);
  if (exists) await ctx.click('[aria-label="New chat"],.new-chat');
  else {
    await ctx.check('initial blank home has no empty saved conversation to replace', '!document.querySelector(".conversation .message--user")');
    if(await ctx.evaluate('Boolean(document.querySelector(".navigation-dialog[open]"))'))await ctx.click('.navigation-dialog[open] [aria-label="Close navigation"]');
  }
}
export async function openPrompts(ctx) {
  await ctx.click('.opal-composer [aria-label="Saved prompts"]');
  await ctx.waitFor('Boolean(document.querySelector(\'.prompt-library-dialog[open] [aria-label="Private saved prompts"]\'))', 'saved_prompts_dialog_ready');
  await ctx.waitFor('!document.querySelector(\'.prompt-library-dialog[open] [aria-label="Private saved prompts"] [role="status"]\')', 'saved_prompts_owned_page_ready');
}
export async function closePrompts(ctx) {
  await ctx.click('.prompt-library-dialog[open] [aria-label="Close saved prompts"]');
  await ctx.waitFor('!document.querySelector(".prompt-library-dialog[open]")', 'saved_prompts_dialog_closed');
}
