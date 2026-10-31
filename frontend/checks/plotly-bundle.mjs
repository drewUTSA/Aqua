// Usage: node checks/plotly-bundle.mjs <Vite dist with --manifest> [P07 dist]
// Reports actual byte counts. It never imports/evaluates the browser engine.
import assert from "node:assert/strict";
import { readFile, lstat,realpath } from "node:fs/promises";
import path from "node:path";
import { gzipSync } from "node:zlib";
import { createHash } from "node:crypto";

const root = path.resolve(process.argv[2] || "dist"), baseline = process.argv[3] && path.resolve(process.argv[3]);
async function asset(directory, name) {
  assert.equal(typeof name, "string"); assert.ok(name.length <= 512 && !name.includes("\\") && !name.includes("\0"));
  const file = path.resolve(directory, name.replace(/^\//, ""));
  assert.ok(file.startsWith(directory + path.sep), "asset_outside_dist");
  const info = await lstat(file); assert.ok(info.isFile() && !info.isSymbolicLink() && info.size <= 8 * 1024 * 1024, "asset_file_rejected");
  for(let cursor=path.dirname(file);;cursor=path.dirname(cursor)){assert.ok(!(await lstat(cursor)).isSymbolicLink(),'asset_symlink_ancestor_rejected');if(cursor===directory)break;}
  const inside=path.relative(await realpath(directory),await realpath(file));assert.ok(inside&&!inside.startsWith('..')&&!path.isAbsolute(inside),'asset_resolved_outside_dist');
  return readFile(file);
}
async function counts(directory, names) {
  const items = [];
  for (const name of [...names].sort()) { const data = await asset(directory, name); items.push({ file: name, bytes: data.length, gzip_bytes: gzipSync(data).length }); }
  return { files: items, bytes: items.reduce((sum, item) => sum + item.bytes, 0), gzip_bytes: items.reduce((sum, item) => sum + item.gzip_bytes, 0) };
}
const raw = await asset(root, ".vite/manifest.json"); assert.ok(raw.length < 100000);
const manifest = JSON.parse(raw), entries = Object.keys(manifest).filter((key) => manifest[key].isEntry);
assert.equal(entries.length, 1, "single_app_entry_required"); assert.ok(Object.keys(manifest).length <= 100);
function walk(keys, dynamic = false, seen = new Set()) {
  for (const key of keys) {
    if (seen.has(key)) continue;
    assert.ok(Object.hasOwn(manifest, key), "manifest_import_missing"); seen.add(key);
    walk([...(manifest[key].imports || []), ...(dynamic ? manifest[key].dynamicImports || [] : [])], dynamic, seen);
  }
  return seen;
}
const initial = walk(entries), reachable = walk(entries, true);
const engines = Object.keys(manifest).filter((key) => /plotly-basic/i.test(key + " " + manifest[key].file));
assert.equal(engines.length, 1, "one_pinned_basic_engine_chunk_required");
assert.ok(!initial.has(engines[0]), "chart_engine_in_initial_bundle"); assert.ok(reachable.has(engines[0]), "chart_engine_unreachable");
const names = new Set(); for (const key of initial) { names.add(manifest[key].file); for (const name of manifest[key].css || []) names.add(name); }
const initialCounts = await counts(root, names), engine = await asset(root, manifest[engines[0]].file);
assert.ok(engine.includes(Buffer.from("4.1.2")), "pinned_engine_version_missing");
assert.ok(engine.length <= 1536 * 1024 && gzipSync(engine).length <= 500 * 1024, "chart_engine_budget_exceeded");
const report = { status: "passed", initial: initialCounts, engine: { file: manifest[engines[0]].file, bytes: engine.length, gzip_bytes: gzipSync(engine).length,
  sha256: createHash("sha256").update(engine).digest("hex"), initial: false }, manifest_sha256: createHash("sha256").update(raw).digest("hex") };
if (baseline) {
  const html = (await asset(baseline, "index.html")).toString(), previous = new Set();
  for (const tag of html.matchAll(/<(?:script|link)\b[^>]*>/g)) {
    if (tag[0].startsWith("<link") && !/rel=["'](?:stylesheet|modulepreload)["']/.test(tag[0])) continue;
    const value = /(?:src|href)=["']([^"']+)["']/.exec(tag[0]); if (value) previous.add(value[1].replace(/^\//, ""));
  }
  assert.ok(previous.size > 0 && previous.size < 30);
  // P07 has no build manifest. Follow its local static ESM imports only; dynamic
  // Recharts/dashboard chunks were also absent from the initial login payload.
  for (const name of previous) {
    if (!name.endsWith(".js")) continue;
    const source = (await asset(baseline, name)).toString();
    for (const match of source.matchAll(/(?:\bimport\s*(?:[^;"']{0,400}?\s*from\s*)?|\bexport\s*[^;"']{0,400}?\s*from\s*)["'](\.[^"']+)["']/g)) {
      previous.add(path.posix.normalize(path.posix.join(path.posix.dirname(name), match[1]))); assert.ok(previous.size < 100);
    }
  }
  const old = await counts(baseline, previous); report.baseline = old;
  report.initial_delta = { bytes: initialCounts.bytes - old.bytes, gzip_bytes: initialCounts.gzip_bytes - old.gzip_bytes };
}
process.stdout.write(JSON.stringify(report, null, 2) + "\n");
