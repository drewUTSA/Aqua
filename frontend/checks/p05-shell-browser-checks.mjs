// Shared presentation checks. Both build variants retain the same security
// journeys; this helper adds no API transport and never reads session material.
export const EXPECTED_SHELL = process.env.AQUA_P05_EXPECTED_SHELL || "opal";
if (!["opal", "legacy"].includes(EXPECTED_SHELL)) throw new Error("expected_shell_invalid");

export async function assertShell(check, quote = JSON.stringify) {
  await check(`operator-selected ${EXPECTED_SHELL} shell is rendered`,
    `document.querySelector('.opal-workspace')?.dataset.uiShell===${quote(EXPECTED_SHELL)}`);
}

export async function capturePerformance(evaluate, label) {
  // Durations are observations, not timing assertions: shared CI hardware is
  // variable. Byte and request budgets below are deterministic delivery limits.
  return evaluate(`(()=>{
    const navigation=performance.getEntriesByType('navigation')[0];
    const number=value=>Number.isFinite(value)?Math.round(value*100)/100:null;
    const resources=performance.getEntriesByType('resource').filter(entry=>new URL(entry.name).origin===location.origin&&!new URL(entry.name).pathname.startsWith('/api/'));
    return {label:${JSON.stringify(label)},viewport:{width:innerWidth,height:innerHeight},
      navigation_ms:number(navigation?.duration),dom_content_loaded_ms:number(navigation?.domContentLoadedEventEnd),
      first_paint_ms:number(performance.getEntriesByName('first-paint')[0]?.startTime),
      first_contentful_paint_ms:number(performance.getEntriesByName('first-contentful-paint')[0]?.startTime),
      static_resources:resources.map(entry=>({path:new URL(entry.name).pathname,bytes:entry.decodedBodySize,elapsed_ms:number(entry.duration)}))};
  })()`);
}

export async function assertLoginDelivery(check) {
  await check("login defers the chart chunk and bounds initial script delivery", `(()=>{
    const resources=performance.getEntriesByType('resource').filter(entry=>new URL(entry.name).origin===location.origin);
    const scripts=resources.filter(entry=>new URL(entry.name).pathname.endsWith('.js'));
    const styles=resources.filter(entry=>new URL(entry.name).pathname.endsWith('.css'));
    const scriptBytes=scripts.reduce((sum,entry)=>sum+entry.decodedBodySize,0);
    return scripts.length>0&&scripts.length<=3&&scriptBytes>0&&scriptBytes<=600000
      &&styles.reduce((sum,entry)=>sum+entry.decodedBodySize,0)<=80000
      &&!resources.some(entry=>/DashboardPreview|PlotlyChart|plotly-basic/i.test(new URL(entry.name).pathname));
  })()`);
}

export async function assertEssentialControls(check, label) {
  await check(label, `(()=>{
    const selectors=['.opal-composer textarea','[aria-label="Send message"]','.workspace-header [aria-label="Account menu"]'];
    return document.documentElement.scrollWidth<=innerWidth+1&&selectors.every(selector=>{
      const el=document.querySelector(selector),rect=el?.getBoundingClientRect();
      if(!rect||rect.width<=0||rect.height<=0||el.closest('[hidden],[inert]'))return false;
      if(rect.left<0||rect.right>innerWidth+1||rect.top<0||rect.bottom>innerHeight+1)return false;
      const top=document.elementFromPoint(rect.left+rect.width/2,rect.top+rect.height/2);
      return top===el||el.contains(top);
    });
  })()`);
}

export async function captureControlBounds(evaluate) {
  // Keep diagnostic output numerical/structural: never serialize field values,
  // message text, account labels, cookies or tokens when an assertion fails.
  return evaluate(`(()=>{
    const selectors=['.opal-composer textarea','[aria-label="Send message"]','.workspace-header [aria-label="Account menu"]'];
    return {viewport:{width:innerWidth,height:innerHeight},page_width:document.documentElement.scrollWidth,
      controls:selectors.map(selector=>{
        const el=document.querySelector(selector),rect=el?.getBoundingClientRect();
        if(!rect)return {selector,exists:false};
        const top=document.elementFromPoint(rect.left+rect.width/2,rect.top+rect.height/2);
        return {selector,exists:true,left:rect.left,right:rect.right,top:rect.top,bottom:rect.bottom,
          width:rect.width,height:rect.height,hidden:Boolean(el.closest('[hidden],[inert]')),
          unobscured:top===el||el.contains(top)};
      })};
  })()`);
}

export async function assertSafeAreaStyles(check) {
  await check("workspace styles reserve all four safe-area insets", `(()=>{
    const collect=rules=>[...rules].flatMap(rule=>[
      ...(rule.selectorText?.includes('.opal-workspace')?[rule.cssText]:[]),
      ...(rule.cssRules?collect(rule.cssRules):[])
    ]);
    const rules=[...document.styleSheets].flatMap(sheet=>collect(sheet.cssRules)).join(' ');
    return ['top','right','bottom','left'].every(edge=>rules.includes('env(safe-area-inset-'+edge));
  })()`);
}

export async function enlargeText(evaluate) {
  await evaluate("(()=>{const nodes=[...document.querySelectorAll('h1,h2,p,label,button,input,textarea,a,small,span,strong')].filter(el=>el.getClientRects().length&&!el.closest('[hidden],[inert]')).map(el=>({el,size:parseFloat(getComputedStyle(el).fontSize),line:parseFloat(getComputedStyle(el).lineHeight)}));for(const {el,size,line} of nodes){el.style.fontSize=`${size*2}px`;if(Number.isFinite(line))el.style.lineHeight=`${line*2}px`;}return true})()");
}
