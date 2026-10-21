import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import SafeMarkdown from "../src/components/chat/SafeMarkdown.js";

const render = (text) => renderToStaticMarkup(React.createElement(SafeMarkdown, null, text));

test("answer formatting keeps useful text, lists and code without executing it", () => {
  const html = render("**Revenue**: 15.\n\n- first\n- second\n\n```javascript\nalert('inert code');\n```");
  assert.match(html, /<strong>Revenue<\/strong>/);
  assert.match(html, /<ul>/);
  assert.match(html, /<pre><code/);
  assert.match(html, /alert/);
  assert.doesNotMatch(html, /<script|<iframe|<svg|<img|\son\w+=/i);
});

for (const target of ["https://attacker.invalid/collect?data=synthetic", "//attacker.invalid/track", "/api/auth/config", "data:image/svg+xml;base64,PHN2Zz4=", "javascript:alert(1)"]) {
  test(`untrusted Markdown cannot make a resource request for ${target.split(":")[0]}`, () => {
    const html = render(`![untrusted image](${target})`);
    assert.doesNotMatch(html, /<img|<link|\ssrc(?:set)?=|\shref=/i);
    assert.doesNotMatch(html, /attacker\.invalid|api\/auth\/config/);
  });
}

for (const target of ["https://attacker.invalid", "//attacker.invalid", "/api/auth/config", "javascript:alert(1)", "mailto:attacker@example.invalid", "xmpp:attacker@example.invalid"]) {
  test(`untrusted links remain inert text for ${target.split(":")[0]}`, () => {
    const html = render(`[Readable label](${target})`);
    assert.match(html, /Readable label/);
    assert.doesNotMatch(html, /<a\b|\shref=|<img|<link/i);
  });
}

test("raw HTML, events, SVG, forms and embedded browsing contexts are discarded", () => {
  const html = render('<img src="https://attacker.invalid/x" onerror="alert(1)">\n<script>alert(1)</script>\n<svg onload="alert(1)"></svg>\n<iframe src="https://attacker.invalid"></iframe>\n<form action="https://attacker.invalid"><input name="password"></form>');
  assert.doesNotMatch(html, /<img|<script|<svg|<iframe|<form|<input|\son\w+=|\ssrc=|\saction=/i);
  assert.doesNotMatch(html, /attacker\.invalid/);
});

test("caller props cannot inject plugins, raw HTML or alternate renderers", () => {
  const html = renderToStaticMarkup(React.createElement(SafeMarkdown, {
    children: "![image](https://attacker.invalid)",
    components: { img: () => React.createElement("script", null, "alert(1)") },
    rehypePlugins: [() => { throw new Error("untrusted plugin was invoked"); }],
    skipHtml: false
  }));
  assert.doesNotMatch(html, /<img|<script|attacker\.invalid/i);
});
