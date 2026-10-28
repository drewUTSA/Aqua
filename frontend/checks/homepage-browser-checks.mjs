import assert from 'node:assert/strict';
import { openAccount, recentsAction } from './homepage-browser-actions.mjs';

const visible="el=>el.getClientRects().length&&!el.closest('[hidden],[inert]')";
export const NEXT_MODEL='fixture-model-next';
export async function initialHomepageChecks(ctx, fixture) {
  const {check,evaluate,click,key,fill,waitFor}=ctx;
  await ctx.cdp.send('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'no-preference'}]});
  await check('homepage initial sidebar contains only Projects and Recents sections', "(()=>{const labels=[...document.querySelectorAll('.desktop-sidebar .opal-sidebar__scroll h2')].map(el=>el.textContent.replace(/[⌄›]/g,'').trim());return JSON.stringify(labels)===JSON.stringify(['Projects','Recents'])&&!document.querySelector('.desktop-sidebar [aria-label=\"Private saved prompts\"]')})()");
  await check('homepage has one bottom account entry and no header account duplicate', `document.querySelectorAll('.workspace-header [aria-label="Account menu"]').length===0&&[...document.querySelectorAll('.opal-account [aria-label="Account menu"]')].filter(${visible}).length===1`);
  await check('homepage has exactly one model chooser across welcome and mobile layouts', `document.querySelectorAll('.model-selector__trigger').length===1&&!document.querySelector('select.mobile-model')`);
  assert.equal(fixture.calls.filter(call=>call.method==='GET'&&['/api/v1/me/saved-prompts','/api/v1/starter-prompts'].includes(call.path)).length,0,'initial_home_must_not_fetch_prompt_libraries');
  await check('homepage defers private saved and starter prompt requests until explicit opening', 'true');
  await fill('.opal-composer textarea','Homepage unsent model-choice draft');
  await evaluate("(()=>{window.__homepageComposer=document.querySelector('.opal-composer textarea');window.__homepageComposerHeight=document.querySelector('.opal-composer').getBoundingClientRect().height;return true})()");
  const submitted=fixture.queryCount();
  await click('.model-selector__trigger');
  await waitFor('Boolean(document.querySelector(\'[role="menu"][aria-label="AI models"]\'))','homepage_model_menu_ready');
  await key('End');
  await check('homepage model menu End reaches the last advertised radio item', `document.activeElement?.getAttribute('role')==='menuitemradio'&&document.activeElement.dataset.modelId==='${NEXT_MODEL}'`);
  await waitFor("document.querySelector('[role=menu][aria-label=\"AI models\"]').getAnimations().every(animation=>animation.playState==='finished')",'homepage_model_menu_reveal_completed');
  await ctx.screenshot('homepage-model-menu-desktop');
  await key('Home'); await key('ArrowDown'); await key('Enter',0,'\r');
  await waitFor('!document.querySelector(\'[role="menu"][aria-label="AI models"]\')','homepage_model_keyboard_selection_committed');
  await check('homepage model selection returns focus and preserves the same unsent composer', `!document.querySelector('[role="menu"][aria-label="AI models"]')&&document.activeElement.matches('.model-selector__trigger')&&document.querySelector('.opal-composer textarea')===window.__homepageComposer&&document.querySelector('.opal-composer textarea').value==='Homepage unsent model-choice draft'&&document.querySelector('.model-selector__name').textContent==='Fixture next model'`);
  assert.equal(fixture.queryCount(),submitted,'model_change_must_not_submit_or_replay');
  await check('homepage model selection alone never submits or restarts analysis','true');
  await openAccount(ctx); await key('End');
  await check('homepage account menu keyboard End reaches Sign out', "document.activeElement?.getAttribute('role')==='menuitem'&&document.activeElement.textContent.trim()==='Sign out'");
  await waitFor("document.querySelector('[role=menu][aria-label=\"Your account\"]').getAnimations().every(animation=>animation.playState==='finished')",'homepage_account_menu_reveal_completed');
  await ctx.screenshot('homepage-account-menu-desktop');
  const logout=fixture.count('/api/auth/logout');
  await key('Enter',0,'\r'); await waitFor('Boolean(document.querySelector(".account-signout-dialog[open]"))','homepage_logout_confirmation');
  await check('homepage sign-out confirmation starts on Keep working', "document.activeElement?.textContent==='Keep working'");
  await key('Tab',8); await check('homepage sign-out confirmation contains reverse keyboard traversal', "document.activeElement?.textContent==='Sign out'&&document.querySelector('.account-signout-dialog').contains(document.activeElement)");
  await key('Escape');
  await check('homepage cancel sign-out retains private state and returns account focus', "!document.querySelector('.account-signout-dialog')&&document.activeElement?.getAttribute('aria-label')==='Account menu'&&document.querySelector('.opal-composer textarea')===window.__homepageComposer&&document.querySelector('.opal-composer textarea').value==='Homepage unsent model-choice draft'");
  assert.equal(fixture.count('/api/auth/logout'),logout,'cancelled_signout_must_not_revoke_or_write');
  await fill('.opal-composer textarea','');
}

export function assertNextSelectedModel(fixture) {
  const last=fixture.calls.filter(call=>call.method==='POST'&&/^\/api\/v1\/chats(?:\/[^/]+\/messages(?:\/[^/]+\/retries)?)?$/.test(call.path)).at(-1);
  assert.equal(last?.body?.model,NEXT_MODEL,'next_explicit_submission_uses_selected_advertised_model');
}

export async function activeHomepageChecks(ctx) {
  await ctx.waitFor('document.querySelector(".opal-composer").getBoundingClientRect().height<window.__homepageComposerHeight-16', 'homepage_composer_compacted');
  await ctx.check('homepage first answer compacts the same textarea and shares the unframed canvas', "(()=>{const el=document.querySelector('.message__bubble--aqua'),s=el&&getComputedStyle(el);return document.querySelector('.opal-composer textarea')===window.__homepageComposer&&Boolean(s)&&s.backgroundColor==='rgba(0, 0, 0, 0)'&&parseFloat(s.borderTopWidth)===0&&parseFloat(s.borderRightWidth)===0&&s.boxShadow==='none'})()");
  await ctx.check('homepage New chat reveal has a short fade with a stable final visible state', "(()=>{const el=document.querySelector('.desktop-sidebar .refined-new-chat'),s=el&&getComputedStyle(el);return Boolean(s)&&s.animationName!=='none'&&parseFloat(s.animationDuration)>0&&parseFloat(s.animationDuration)<=.3})()");
  await ctx.check('homepage New chat uses a visible theme-colored plus mask and a reachable target', "(()=>{const button=document.querySelector('.desktop-sidebar .refined-new-chat'),icon=button?.querySelector('.icon-contrast'),r=button?.getBoundingClientRect(),i=icon?.getBoundingClientRect(),s=icon&&getComputedStyle(icon);return r&&i&&r.height>=43.9&&i.width>=15.9&&i.height>=15.9&&s.display!=='none'&&s.maskImage!=='none'&&s.backgroundColor!=='rgba(0, 0, 0, 0)'&&s.backgroundColor!==getComputedStyle(button).backgroundColor})()");
}

export async function mobileHomepageChecks(ctx) {
  const {check,click,evaluate,key,waitFor}=ctx;
  const before=await evaluate("({font:document.documentElement.style.fontSize,text:parseFloat(getComputedStyle(document.querySelector('.opal-composer textarea')).fontSize)})");
  await click('.model-selector__trigger');
  const modelBase=await evaluate("parseFloat(getComputedStyle(document.querySelector('.model-selector__option-name')).fontSize)");
  await key('Escape');await openAccount(ctx);
  const accountBase=await evaluate("parseFloat(getComputedStyle(document.querySelector('.account-menu__panel [role=menuitem] > span')).fontSize)");
  const menuTextAudit=ctx.homepageMenuTextAudit||{};ctx.homepageMenuTextAudit=menuTextAudit;
  Object.assign(menuTextAudit,{model_base_pixels:modelBase,account_base_pixels:accountBase});
  await key('Escape');await key('Escape');await waitFor('!document.querySelector(".navigation-dialog[open]")','homepage_baseline_navigation_closed');
  await evaluate("(async()=>{document.documentElement.style.fontSize='200%';await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));return true})()");
  await check('homepage reflows at 320 CSS pixels with actual composer text doubled', `document.documentElement.scrollWidth<=innerWidth+1&&innerWidth===320&&parseFloat(getComputedStyle(document.querySelector('.opal-composer textarea')).fontSize)>=${before.text*1.99}`);
  await click('.model-selector__trigger');
  const modelEnlarged=await evaluate("parseFloat(getComputedStyle(document.querySelector('.model-selector__option-name')).fontSize)");
  Object.assign(menuTextAudit,{model_enlarged_pixels:modelEnlarged,model_scale:modelEnlarged/modelBase});
  await check('homepage model menu labels actually double with 200 percent root text',String(modelEnlarged>=modelBase*1.99));
  await key('End');
  await check('homepage mobile model menu keeps its last keyboard item reachable',"(()=>{const m=document.querySelector('[role=menu][aria-label=\"AI models\"]'),el=document.activeElement,r=el?.getBoundingClientRect(),p=m?.getBoundingClientRect();return p&&r&&m.contains(el)&&el.matches('[role=menuitemradio]:last-of-type')&&r.top>=p.top&&r.bottom<=p.bottom+1})()");
  await check('homepage mobile model menu stays inside the viewport at doubled text', "(()=>{const el=document.querySelector('[role=menu][aria-label=\"AI models\"]'),r=el?.getBoundingClientRect();return r&&r.width>0&&r.left>=0&&r.right<=innerWidth+1&&r.top>=0&&r.bottom<=innerHeight+1&&[...el.querySelectorAll('[role=menuitemradio]')].every(item=>item.getBoundingClientRect().height>=43.9)})()");
  await waitFor("document.querySelector('[role=menu][aria-label=\"AI models\"]').getAnimations().every(animation=>animation.playState==='finished')",'homepage_mobile_model_reveal_completed');
  await ctx.screenshot('homepage-model-menu-mobile-double-text');
  await key('Escape');
  menuTextAudit.composer_controls=await evaluate("(()=>{const rect=selector=>{const r=document.querySelector(selector)?.getBoundingClientRect();if(!r)return null;return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height}};return {composer:rect('.opal-composer'),model:rect('.opal-composer .model-selector__trigger'),prompts:rect('.opal-composer [aria-label=\"Saved prompts\"]'),send:rect('.opal-composer [aria-label=\"Send message\"]')}})()");
  const controls=menuTextAudit.composer_controls;
  const contained=controls.composer&&['model','prompts','send'].every(name=>{const r=controls[name],p=controls.composer;return r&&r.width>0&&r.height>0&&r.left>=p.left-.5&&r.right<=p.right+.5&&r.top>=p.top-.5&&r.bottom<=p.bottom+.5});
  await check('homepage doubled-text model prompt and send controls stay separate inside the composer',String(Boolean(contained&&controls.model.right<=controls.prompts.left+.5&&controls.prompts.right<=controls.send.left+.5)));
  await openAccount(ctx);
  const accountEnlarged=await evaluate("parseFloat(getComputedStyle(document.querySelector('.account-menu__panel [role=menuitem] > span')).fontSize)");
  Object.assign(menuTextAudit,{account_enlarged_pixels:accountEnlarged,account_scale:accountEnlarged/accountBase});
  await check('homepage account menu labels actually double with 200 percent root text',String(accountEnlarged>=accountBase*1.99));
  await key('End');
  await check('homepage mobile account menu keeps its last keyboard item reachable',"(()=>{const m=document.querySelector('[role=menu][aria-label=\"Your account\"]'),el=document.activeElement,r=el?.getBoundingClientRect(),p=m?.getBoundingClientRect();return p&&r&&m.contains(el)&&el.textContent.trim()==='Sign out'&&r.top>=p.top&&r.bottom<=p.bottom+1})()");
  await check('homepage mobile bottom account menu stays inside the viewport at doubled text', "(()=>{const el=document.querySelector('[role=menu][aria-label=\"Your account\"]'),r=el?.getBoundingClientRect();return r&&r.width>0&&r.left>=0&&r.right<=innerWidth+1&&r.top>=0&&r.bottom<=innerHeight+1})()");
  await waitFor("document.querySelector('[role=menu][aria-label=\"Your account\"]').getAnimations().every(animation=>animation.playState==='finished')",'homepage_mobile_account_reveal_completed');
  await ctx.screenshot('homepage-account-menu-mobile-double-text');
  await key('Escape'); await click('.navigation-dialog[open] [aria-label="Recents actions"]');
  await key('End');
  await check('homepage mobile Recents menu exposes a bounded keyboard-reachable final action', "(()=>{const el=document.querySelector('.navigation-dialog[open] [role=menu]'),r=el?.getBoundingClientRect();return r&&el.contains(document.activeElement)&&r.left>=0&&r.right<=innerWidth+1&&r.top>=0&&r.bottom<=innerHeight+1})()");
  await key('Escape');
  await recentsAction(ctx,'Search chats');
  await ctx.fill('.navigation-dialog .refined-search-dialog input','Mobile unsent title query');
  await ctx.cdp.send('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});
  await waitFor('!document.querySelector(".navigation-dialog[open]")&&!document.querySelector(".navigation-dialog .refined-search-dialog[open]")','homepage_nested_dialog_suppressed');
  await check('homepage closing the native navigation ancestor closes its private top-layer dialog', '!document.querySelector(".navigation-dialog[open],.navigation-dialog dialog[open]")');
  await ctx.cdp.send('Emulation.setDeviceMetricsOverride',{width:320,height:844,deviceScaleFactor:1,mobile:true});
  await click('[aria-label="Open navigation"]');
  await waitFor('Boolean(document.querySelector(".navigation-dialog .refined-search-dialog[open]"))','homepage_nested_dialog_restored');
  await check('homepage restoring navigation retains its unsent search without submitting it', 'document.querySelector(".navigation-dialog .refined-search-dialog input").value==="Mobile unsent title query"');
  await ctx.clickText('Close search','.navigation-dialog .refined-search-dialog button');
  await key('Escape'); await waitFor('!document.querySelector(".navigation-dialog[open]")','homepage_mobile_navigation_closed');
  await ctx.cdp.send('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});
  await check('homepage reduced motion removes transitions and animations from visible workspace controls', `matchMedia('(prefers-reduced-motion: reduce)').matches&&[...document.querySelectorAll('.opal-composer,.model-selector__trigger,.navigation-toggle')].filter(${visible}).every(el=>{const s=getComputedStyle(el);return s.animationName==='none'&&s.transitionDuration.split(',').every(t=>parseFloat(t)===0)})`);
  await ctx.cdp.send('Emulation.setEmulatedMedia',{features:[]});
  await evaluate(`(()=>{document.documentElement.style.fontSize=${JSON.stringify(before.font)};return true})()`);
}

export async function actualHomepageStateChecks(ctx) {
  const {check,evaluate,click,clickText,waitFor}=ctx;
  const before=ctx.queryCount();
  await evaluate("(()=>{window.__homepageActualComposer=document.querySelector('.opal-composer textarea');window.__homepageActualReading=document.querySelector('.conversation__scroll')?.scrollTop||0;return true})()");
  await check('actual homepage has one compact composer model chooser and one bottom account entry', `document.querySelectorAll('.model-selector__trigger').length===1&&document.querySelectorAll('.workspace-header [aria-label="Account menu"]').length===0&&[...document.querySelectorAll('.opal-account [aria-label="Account menu"]')].filter(${visible}).length===1&&Boolean(document.querySelector('.opal-chat--active'))`);
  await openAccount(ctx); await clickText('Sign out','[role="menuitem"]');
  await waitFor('Boolean(document.querySelector(".account-signout-dialog[open]"))','actual_homepage_logout_review');
  await clickText('Keep working','.account-signout-dialog button');
  await check('actual homepage cancelled account action preserves unsent text composer and reading position', "document.querySelector('.opal-composer textarea')===window.__homepageActualComposer&&document.querySelector('.opal-composer textarea').value==='Actual homepage unsent draft'&&Math.abs((document.querySelector('.conversation__scroll')?.scrollTop||0)-window.__homepageActualReading)<=1&&!document.querySelector('.account-signout-dialog')");
  assert.equal(ctx.queryCount(),before,'actual_account_review_cannot_submit_analysis');
}
