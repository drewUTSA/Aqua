// JSON.parse discards duplicate keys. This bounded grammar pass rejects them
// before parsing so the import review cannot silently omit submitted fields.
export function assertUniqueJsonKeys(text) {
  let index = 0;
  const fail = () => { throw new Error("Choose JSON without duplicate fields or unsupported nesting."); };
  const whitespace = () => { while (index < text.length && /[\t\r\n ]/.test(text[index])) index++; };
  const string = () => {
    const start = index++;
    while (index < text.length) {
      if (text[index] === "\\") { index += 2; continue; }
      if (text[index++] === '"') return JSON.parse(text.slice(start, index));
    }
    return fail();
  };
  const scalar = /(?:true|false|null|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)/y;
  const value = (depth) => {
    whitespace(); if (depth > 4) fail();
    const character = text[index];
    if (character === '"') { string(); return; }
    if (character === "{" || character === "[") {
      const object = character === "{", end = object ? "}" : "]", keys = new Set(); let count = 0;
      index++; whitespace(); if (text[index] === end) { index++; return; }
      while (index < text.length) {
        if (++count > 64) fail();
        if (object) {
          whitespace(); if (text[index] !== '"') fail(); const key = string();
          if (keys.has(key)) fail(); keys.add(key); whitespace(); if (text[index++] !== ":") fail();
        }
        value(depth + 1); whitespace(); const separator = text[index++];
        if (separator === end) return;
        if (separator !== ",") fail();
      }
      fail();
    }
    scalar.lastIndex = index;
    if (!scalar.test(text)) fail(); index = scalar.lastIndex;
  };
  value(0); whitespace(); if (index !== text.length) fail();
}
