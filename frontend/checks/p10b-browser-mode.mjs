export const SECURE_ACCOUNT_ORIGIN = "https://aqua-browser.example.test";
export function browserFixtureMode(options) {
  if (options === undefined) return { secureAccountFixture: false };
  if (!options || typeof options !== "object" || Array.isArray(options) || ![Object.prototype, null].includes(Object.getPrototypeOf(options))) throw Error("fixture_mode_invalid");
  const keys = Reflect.ownKeys(options);
  if (keys.some(key => key !== "secureAccountFixture" || !Object.hasOwn(Object.getOwnPropertyDescriptor(options, key), "value"))
    || Object.hasOwn(options, "secureAccountFixture") && typeof options.secureAccountFixture !== "boolean") throw Error("fixture_mode_invalid");
  return { secureAccountFixture: options.secureAccountFixture === true };
}

// Secure mode uses the same frozen byte map as HTTP. This account fixture
// is a reserved-origin CDP simulation, not a DNS/socket/TLS transport test.
export function staticFixtureResponse(files, url) {
  if (url.origin !== SECURE_ACCOUNT_ORIGIN) throw Error("secure_static_origin_invalid");
  const pathname = url.pathname, key = pathname.startsWith("/api/") ? null : files.has(pathname) ? pathname : !/\.[^/]*$/.test(pathname) ? "/index.html" : null;
  const bytes = key && files.get(key), status = bytes ? 200 : pathname === "/favicon.ico" ? 204 : 404;
  const extension = key?.slice(key.lastIndexOf("."));
  const type = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".woff2": "font/woff2", ".svg": "image/svg+xml" }[extension] || "application/octet-stream";
  return { status, headers: [{ name: "Content-Type", value: type }, { name: "Cache-Control", value: "no-store" },
    { name: "X-Content-Type-Options", value: "nosniff" }, { name: "Referrer-Policy", value: "no-referrer" }],
    ...(status === 204 ? {} : { body: bytes ? bytes.toString("base64") : "" }) };
}
