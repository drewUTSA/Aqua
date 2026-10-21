import React from "react";
import ReactMarkdown from "react-markdown";

// Result text can contain database values. It may format text, but must never
// select a network destination, navigate, embed content or install a renderer.
const formatting = Object.freeze([
  "p", "br", "strong", "em", "del", "ul", "ol", "li", "blockquote",
  "pre", "code", "hr", "h1", "h2", "h3", "h4", "h5", "h6", "a"
]);

function InertLink({ children }) {
  return React.createElement(React.Fragment, null, children);
}

/** Render untrusted answer text through a fixed, formatting-only policy. */
export default function SafeMarkdown({ children }) {
  return React.createElement(ReactMarkdown, {
    allowedElements: formatting,
    unwrapDisallowed: true,
    skipHtml: true,
    remarkRehypeOptions: { allowDangerousHtml: false },
    // No generated URL is an authorized action, including relative API URLs.
    urlTransform: () => "",
    components: { a: InertLink }
  }, typeof children === "string" ? children : "");
}
