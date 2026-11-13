import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, mkdir, writeFile, realpath, lstat, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const checker = fileURLToPath(new URL("./plotly-bundle.mjs", import.meta.url));
async function checkBudget(scriptBytes, styleBytes) {
  const root = await mkdtemp(path.join(tmpdir(), "aqua-initial-delivery-"));
  try {
    await mkdir(path.join(root, "assets")); await mkdir(path.join(root, ".vite"));
    const manifest = { "src/main.jsx": { file: "assets/main.js", isEntry: true, css: ["assets/main.css"], dynamicImports: ["engine"] },
      engine: { file: "assets/plotly-basic.js" } };
    await writeFile(path.join(root, ".vite/manifest.json"), JSON.stringify(manifest));
    await writeFile(path.join(root, "assets/main.js"), Buffer.alloc(scriptBytes, 32));
    await writeFile(path.join(root, "assets/main.css"), Buffer.alloc(styleBytes, 32));
    await writeFile(path.join(root, "assets/plotly-basic.js"), "/* fixture engine version 4.1.2 */");
    return spawnSync(process.execPath, [checker, root], { encoding: "utf8", timeout: 10000, maxBuffer: 65536 });
  } finally {
    const relative = path.relative(await realpath(tmpdir()), await realpath(root));
    assert.ok(relative && !relative.startsWith("..") && !path.isAbsolute(relative) && path.basename(relative).startsWith("aqua-initial-delivery-"));
    assert.equal((await lstat(root)).isSymbolicLink(), false);
    await rm(root, { recursive: true, force: true });
  }
}

test("artifact delivery accepts the exact retained JS and CSS boundaries", async () => {
  const result = await checkBudget(600000, 80000);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).status, "passed");
});
test("one extra initial script byte fails before a browser journey", async () => {
  const result = await checkBudget(600001, 80000);
  assert.notEqual(result.status, 0); assert.match(result.stderr, /initial_script_budget_exceeded/);
});
test("one extra initial stylesheet byte fails before a browser journey", async () => {
  const result = await checkBudget(600000, 80001);
  assert.notEqual(result.status, 0); assert.match(result.stderr, /initial_style_budget_exceeded/);
});
