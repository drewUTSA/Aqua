import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile, readdir } from "node:fs/promises";
import test from "node:test";
import { LOCAL_PATHS, pageDescription } from "../src/services/routes.js";

const html = await readFile(new URL("../index.html", import.meta.url), "utf8");
const folder = new URL("../src/assets/brand/", import.meta.url);
const tags = [...html.matchAll(/<(?:link|meta)\s+[^>]+>/g)].map(([tag]) =>
  Object.fromEntries([...tag.matchAll(/([\w:-]+)="([^"]+)"/g)].map(([, key, value]) => [key, value])));
const social = new Map(tags.filter(tag => tag.property).map(tag => [tag.property, tag.content]));

test("restricted pages offer one static brand preview without indexing or route-specific sharing", () => {
  assert.equal(tags.find(tag => tag.name === "robots").content, "noindex, nofollow");
  assert.equal(social.get("og:type"), "website");
  assert.equal(social.get("og:url"), "https://aqua-ai.us/");
  assert.equal(social.get("og:title"), "AQUA — Automatic Query AI");
  assert.equal(social.get("og:description"), "Ask questions about data you have permission to use.");
  assert.match(social.get("og:image:alt"), /AQUA wordmark.*water droplet.*waves/);
  assert.equal(tags.find(tag => tag.name === "twitter:card").content, "summary_large_image");
});

test("the tab icons, touch icon and brand preview match their declared sizes and immutable filenames", async () => {
  const icons = tags.filter(tag => tag.rel === "icon" || tag.rel === "apple-touch-icon");
  assert.deepEqual(icons.map(tag => [tag.rel, tag.sizes]), [["icon", "16x16"], ["icon", "32x32"], ["apple-touch-icon", "180x180"]]);
  const image = new URL(social.get("og:image"));
  assert.equal(image.origin, "https://aqua-ai.us");
  assert.equal(image.search + image.hash, "");
  assert.equal(social.get("og:image:type"), "image/png");
  assert.equal(social.get("og:image:width"), "1200");
  assert.equal(social.get("og:image:height"), "630");
  const images = icons.map(tag => ({ path: tag.href, size: tag.sizes.split("x").map(Number) }));
  images.push({ path: image.pathname, size: [1200, 630] });
  const names = [];
  for (const item of images) {
    const [, name, hash] = /^\/assets\/(aqua-[\w-]+-([a-f0-9]{12})\.png)$/.exec(item.path);
    const bytes = await readFile(new URL(name, folder));
    assert.equal(createHash("sha256").update(bytes).digest("hex").slice(0, 12), hash);
    assert.equal(bytes.subarray(0, 16).toString("hex"), "89504e470d0a1a0a0000000d49484452");
    assert.deepEqual([bytes.readUInt32BE(16), bytes.readUInt32BE(20)], item.size);
    names.push(name);
  }
  assert.deepEqual((await readdir(folder)).sort(), names.sort());
});

test("each allowed route has fixed public copy and unknown input receives only the generic fallback", () => {
  const unknown = pageDescription("/missing");
  for (const path of LOCAL_PATHS) assert.notEqual(pageDescription(path), unknown);
  assert.notEqual(pageDescription("/privacy"), pageDescription("/terms"));
  assert.notEqual(pageDescription("/settings"), pageDescription("/"));
  for (const path of ["/missing/private-note", "/settings?email=example", "/verify-email#sample", "constructor"]) {
    assert.equal(pageDescription(path), unknown);
  }
});
