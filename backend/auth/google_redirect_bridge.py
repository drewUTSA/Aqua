"""First-party redirect document, with no runtime or storage dependency."""

import json
import secrets


def document(body: dict[str, str]) -> tuple[str, dict[str, str]]:
    nonce = secrets.token_urlsafe(24)
    data = (
        json.dumps(body, ensure_ascii=True)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    # No credential in URLs, storage, diagnostics, third-party resources or a
    # replayable automatic retry. Remove its script node as soon as it executes.
    html = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Completing sign-in | AQUA</title>
<main><h1>Completing your sign-in</h1><p id="status" role="status">Please wait while AQUA checks your browser session.</p><p><a href="/">Check your session</a> · <a href="/signin">Back to sign in</a></p></main>
<script nonce="NONCE">document.currentScript.remove();let body=PAYLOAD;
const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),30000);
const clear=()=>{body.credential='';body.g_csrf_token='';};
addEventListener('pagehide',()=>{controller.abort();clear();},{once:true});
(async()=>{try{
const options={credentials:'same-origin',mode:'same-origin',cache:'no-store',redirect:'error',referrerPolicy:'no-referrer',signal:controller.signal};
const state=await fetch('/api/auth/google/redirect-state',options);
if(!state.ok)throw Error();const config=await state.json();
if(typeof config.csrf_token!=='string'||config.csrf_token.length>256)throw Error();
const result=await fetch('/api/auth/google/redirect-complete',{...options,method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':config.csrf_token},body:JSON.stringify(body)});
if(!result.ok)throw Error();location.replace('/');
}catch{document.getElementById('status').textContent='AQUA could not confirm sign-in. Check your session or return to sign in. Your sign-in will not be retried automatically.';}
finally{clearTimeout(timer);clear();}})();</script></html>"""
    return (
        html.replace("PAYLOAD", data, 1).replace("NONCE", nonce, 1),
        {
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Content-Security-Policy": f"default-src 'none'; script-src 'nonce-{nonce}'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
        },
    )
