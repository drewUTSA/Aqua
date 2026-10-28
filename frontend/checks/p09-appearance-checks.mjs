// Finite UI-only cartesian audit. No Save, request, grant or analysis operation.
export async function checkSettingsAccessibilityTree(ctx) {
  ctx.stage = 'settings_accessibility_tree';
  const tree = await ctx.cdp.send('Accessibility.getFullAXTree');
  const nodes = tree.nodes.filter(node => !node.ignored);
  const named = (role, name) => nodes.some(node => node.role?.value === role && node.name?.value === name);
  const selects = ['Theme', 'Accent', 'Contrast', 'Text size', 'Interface density'];
  ctx.accessibilityTreeAudit = { unignored_nodes: nodes.length, settings_heading: named('heading', 'Settings'),
    category_navigation: named('navigation', 'Settings categories'), named_comboboxes: selects.filter(name => named('combobox', name)).length,
    save_named: named('button', 'Save changes'), cancel_named: named('button', 'Cancel changes') };
  if (!ctx.accessibilityTreeAudit.settings_heading || !ctx.accessibilityTreeAudit.category_navigation || ctx.accessibilityTreeAudit.named_comboboxes !== selects.length || !ctx.accessibilityTreeAudit.save_named || !ctx.accessibilityTreeAudit.cancel_named) throw Error('settings_accessibility_tree_invalid');
  ctx.results.push({ check: 'The browser accessibility tree exposes the Settings heading, category navigation and named form/save controls', passed: true });
}

export async function checkAppearancePresets(ctx) {
  ctx.stage = 'appearance_128_presets';
  ctx.appearanceAudit = await ctx.evaluate(`(async()=>{
    const original=Object.fromEntries(['accent','theme','contrast','density','text_scale'].map(key=>[key,document.querySelector('#settings-field-'+key).value]));
    const frame=()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
    const choose=(key,value)=>{const el=document.querySelector('#settings-field-'+key);if(!el||el.disabled)throw Error();Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(el,String(value));el.dispatchEvent(new Event('change',{bubbles:true}));};
    const parse=color=>{const parts=color.match(/[\\d.]+/g)?.map(Number);if(!parts||parts.length<3)throw Error();return [parts[0],parts[1],parts[2],parts[3]??1];};
    const blend=(top,bottom)=>top.slice(0,3).map((value,i)=>value*top[3]+bottom[i]*(1-top[3]));
    const background=el=>{const layers=[];for(let node=el;node;node=node.parentElement){const color=parse(getComputedStyle(node).backgroundColor);layers.push(color);if(color[3]===1)break;}return layers.reverse().reduce((base,color)=>blend(color,base),[255,255,255]);};
    const luminance=rgb=>rgb.map(value=>value/255).map(value=>value<=.04045?value/12.92:((value+.055)/1.055)**2.4).reduce((sum,value,i)=>sum+value*[.2126,.7152,.0722][i],0);
    const contrast=el=>{const bg=background(el),fg=blend(parse(getComputedStyle(el).color),bg),a=luminance(fg),b=luminance(bg);return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);};
    let cases=0,selectContrast=Infinity,buttonContrast=Infinity,labelContrast=Infinity,breadcrumbContrast=Infinity,sidebarContrast=Infinity,sidebarCases=0,minimumHeight=Infinity,minimumWidth=Infinity;const failures=[];
    for(const accent of ['pearl','sage','slate','amber'])for(const theme of ['opal','light'])for(const contrastMode of ['standard','increased'])for(const density of ['comfortable','compact'])for(const textScale of [100,112.5,125,150]){
      for(const [key,value]of Object.entries({accent,theme,contrast:contrastMode,density,text_scale:textScale}))choose(key,value);
      await frame();
      const selects=[...document.querySelectorAll('.settings-category-section select')],primary=document.querySelector('.settings-savebar button.opal-primary');
      const button=primary.disabled?document.querySelector('.settings-preview button'):primary;
      const ratios=selects.map(contrast),buttonRatio=contrast(button),rectangles=[...selects,button].map(el=>el.getBoundingClientRect());
      const lowSelect=Math.min(...ratios),height=Math.min(...rectangles.map(rect=>rect.height)),width=Math.min(...rectangles.map(rect=>rect.width));
      const labels=[...document.querySelectorAll('.settings-control label[for]')].filter(el=>el.getClientRects().length);
      const lowLabel=Math.min(...labels.map(contrast)),crumb=contrast(document.querySelector('.workspace-header .breadcrumb strong'));
      const sidebar=[...document.querySelectorAll('.desktop-sidebar .sidebar-search input')].filter(el=>el.getClientRects().length&&!el.disabled);
      const lowSidebar=sidebar.length?Math.min(...sidebar.map(contrast)):Infinity;
      labelContrast=Math.min(labelContrast,lowLabel);breadcrumbContrast=Math.min(breadcrumbContrast,crumb);sidebarContrast=Math.min(sidebarContrast,lowSidebar);if(sidebar.length)sidebarCases++;
      selectContrast=Math.min(selectContrast,lowSelect);buttonContrast=Math.min(buttonContrast,buttonRatio);minimumHeight=Math.min(minimumHeight,height);minimumWidth=Math.min(minimumWidth,width);cases++;
      if((lowSelect<4.5||buttonRatio<4.5||lowLabel<4.5||crumb<4.5||lowSidebar<4.5||height<43.9||width<43.9)&&failures.length<8)failures.push({accent,theme,contrast:contrastMode,density,text_scale:textScale,select_contrast:lowSelect,button_contrast:buttonRatio,label_contrast:lowLabel,breadcrumb_contrast:crumb,sidebar_input_contrast:sidebar.length?lowSidebar:null,min_height:height,min_width:width});
    }
    return {cases,expected_cases:128,minimum_select_text_contrast:selectContrast,minimum_enabled_button_text_contrast:buttonContrast,minimum_label_text_contrast:labelContrast,minimum_breadcrumb_text_contrast:breadcrumbContrast,sidebar_input_cases:sidebarCases,minimum_sidebar_input_text_contrast:sidebarCases?sidebarContrast:null,minimum_control_height:minimumHeight,minimum_control_width:minimumWidth,failures,original,disabled_primary_buttons_exempt:true};
  })()`);
  if (ctx.appearanceAudit.cases !== 128 || ctx.appearanceAudit.failures.length) throw Error('appearance_preset_audit_failed');
  ctx.results.push({ check: 'All 128 presets retain measured 4.5:1 control, label, breadcrumb and available sidebar-input contrast with 44px form controls', passed: true });
  await ctx.screenshot('settings-light-increased');
  await ctx.clickText('Cancel changes');
  await ctx.check('Cancel restores every previewed Appearance value without saving', `(()=>{const saved=${JSON.stringify(ctx.appearanceAudit.original)};return Object.entries(saved).every(([key,value])=>document.querySelector('#settings-field-'+key).value===value)})()`);
  await ctx.evaluate("(()=>{const el=document.querySelector('#settings-field-theme');Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(el,'system');el.dispatchEvent(new Event('change',{bubbles:true}));return true})()");
  for (const scheme of ['dark', 'light']) {
    await ctx.cdp.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: scheme }] });
    const theme = scheme === 'dark' ? 'opal' : 'light';
    await ctx.waitFor(`document.querySelector('.opal-workspace').dataset.theme==='${theme}'`, 'system_theme_resolves_' + scheme);
    await ctx.check(`Follow device preference resolves to the ${scheme} system theme`, `document.querySelector('#settings-field-theme').value==='system'&&document.querySelector('.opal-workspace').dataset.theme==='${theme}'`);
  }
  if (ctx.appearanceAudit.original.theme !== 'system') await ctx.clickText('Cancel changes');
  ctx.appearanceAudit.system_theme_modes = ['dark', 'light'];
  await ctx.cdp.send('Emulation.setEmulatedMedia', { features: [{ name: 'forced-colors', value: 'active' }, { name: 'prefers-reduced-motion', value: 'reduce' }] });
  await ctx.waitFor("matchMedia('(forced-colors: active)').matches&&matchMedia('(prefers-reduced-motion: reduce)').matches", 'system_accessibility_media_active');
  await ctx.check('Forced colors and reduced motion preserve named usable Settings controls', "(()=>{const controls=[...document.querySelectorAll('.settings-category-section select')];return controls.length>0&&controls.every(el=>{const s=getComputedStyle(el),r=el.getBoundingClientRect();return el.labels?.length>0&&r.height>=43.9&&s.color!==s.backgroundColor&&s.animationName==='none'&&s.transitionDuration.split(',').every(value=>parseFloat(value)===0)})})()");
  ctx.appearanceAudit.forced_colors_and_reduced_motion = true;
  await ctx.cdp.send('Emulation.setEmulatedMedia', { features: [] });
}

export async function checkMobileCategories(ctx) {
  const categories = [['appearance','Appearance'],['workspace','Workspace'],['chat','Chat & AI'],['charts','Charts & tables'],['accessibility','Accessibility'],['notifications','Notifications'],['region','Language & region'],['account','Account & security'],['privacy','Privacy & data']];
  ctx.mobileOverflowAudit = [];
  ctx.mobileCategoryAudit = { width_css_pixels: 320, root_text_scale_percent: 200, categories: [], reflow_failures: [], all_reachable: false };
  for (const [id, title] of categories) {
    await ctx.clickText('All settings categories');
    await ctx.waitFor(`(()=>{const el=document.querySelector('[data-settings-category="${id}"]');return el&&el.getClientRects().length>0})()`, 'mobile_category_index_ready');
    await ctx.evaluate(`document.querySelector('[data-settings-category="${id}"]').scrollIntoView({block:'center'});true`);
    await ctx.check(`The ${title} category is reachable at 320px with doubled root text`, `(()=>{const r=document.querySelector('[data-settings-category="${id}"]').getBoundingClientRect();return r.width>0&&r.height>=43.9&&r.left>=-1&&r.right<=innerWidth+1})()`);
    await ctx.click(`[data-settings-category='${id}']`);
    await ctx.waitFor(`document.querySelector('#settings-section-heading')?.textContent===${JSON.stringify(title)}&&document.querySelector('.settings-page').dataset.mobileIndex==='false'&&document.querySelector('.settings-content').getClientRects().length>0`, 'mobile_category_content_ready');
    const metrics = await ctx.evaluate(`(()=>{
      const page=document.querySelector('.settings-page'),box=page.getBoundingClientRect(),round=value=>Math.round(value*100)/100;
      const elements=[...page.querySelectorAll('*')].filter(el=>el.getClientRects().length>0).map(el=>{
        const r=el.getBoundingClientRect(),style=getComputedStyle(el);
        return {tag:el.tagName.toLowerCase(),classes:(el.getAttribute('class')||'').replace(/[^a-zA-Z0-9_ -]/g,'').slice(0,160),client_width:el.clientWidth,scroll_width:el.scrollWidth,left:round(r.left),right:round(r.right),width:round(r.width),height:round(r.height),text_length:Math.min(500000,el.textContent?.length||0),overflow_x:['visible','auto','scroll','hidden','clip'].includes(style.overflowX)?style.overflowX:'other'};
      }).filter(el=>el.right>box.right+1||el.left<box.left-1||el.scroll_width>el.client_width+1).sort((a,b)=>Math.max(b.right-box.right,b.scroll_width-b.client_width)-Math.max(a.right-box.right,a.scroll_width-a.client_width)).slice(0,12);
      return {document_client_width:document.documentElement.clientWidth,document_scroll_width:document.documentElement.scrollWidth,viewport_width:innerWidth,page_client_width:page.clientWidth,page_scroll_width:page.scrollWidth,page_left:round(box.left),page_right:round(box.right),overflowing_elements:elements};
    })()`);
    ctx.mobileOverflowAudit.push({ category: id, ...metrics });
    if (ctx.external || ctx.runtimeErrors || ctx.consoleLeaks || ctx.errors.length || ctx.cdp.failure) throw Error('browser_boundary_failure');
    const reflows = metrics.document_scroll_width <= metrics.viewport_width + 1 && metrics.page_scroll_width <= metrics.page_client_width + 1;
    ctx.results.push({ check: `The ${title} content reflows within the narrow viewport`, passed: reflows });
    ctx.mobileCategoryAudit.categories.push(id);
    if (!reflows) {
      ctx.mobileCategoryAudit.reflow_failures.push({ category: id, document_scroll_width: metrics.document_scroll_width, viewport_width: metrics.viewport_width, page_client_width: metrics.page_client_width, page_scroll_width: metrics.page_scroll_width });
      await ctx.screenshot('settings-mobile-overflow-' + id);
    }
  }
  ctx.mobileCategoryAudit.all_reachable = ctx.mobileCategoryAudit.categories.length === 9 && ctx.mobileCategoryAudit.reflow_failures.length === 0;
  if (!ctx.mobileCategoryAudit.all_reachable) { ctx.stage = 'mobile_category_reflow_failed'; throw Error('mobile_category_reflow_failed'); }
}
