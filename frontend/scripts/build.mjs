import assert from "node:assert/strict";
import path from "node:path";
import { readFileSync } from "node:fs";
import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { parseEnv } from "node:util";
import { rspack } from "@rspack/core";

export const root = fileURLToPath(new URL("../", import.meta.url));
export const dist = path.join(root, "dist");
const browserBaseline = ["chrome 107", "edge 107", "firefox 104", "safari 16"];

export function publicBuildEnv(directory, mode, environment) {
  const fileValues = Object.create(null);
  for (const name of [".env", ".env.local", `.env.${mode}`, `.env.${mode}.local`]) {
    try { Object.assign(fileValues, parseEnv(readFileSync(path.join(directory, name), "utf8"))); }
    catch (error) { if (error.code !== "ENOENT") throw error; }
  }
  const value = key => environment[key] ?? fileValues[key];
  return {
    VITE_AQUA_UI_SHELL: value("VITE_AQUA_UI_SHELL") === "legacy" ? "legacy" : "opal",
    VITE_AQUA_DEMO_MODE: String(value("VITE_AQUA_DEMO_MODE") === "true"),
    VITE_AQUA_USE_MOCK: String(value("VITE_AQUA_USE_MOCK") === "true"),
  };
}

export function makeCompiler({ directory = dist, deletionFixture = false, dev = false } = {}) {
  const mode = dev ? "development" : "production";
  const buildEnv = publicBuildEnv(root, mode, process.env);
  const html = deletionFixture
    ? { templateContent: '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Deletion fixture</title></head><body><div id="root"></div></body></html>' }
    : { template: path.join(root, "index.html") };
  return rspack({
    context: root, entry: deletionFixture ? "./checks/deletion-browser-fixture.jsx" : "./src/main.jsx",
    mode, devtool: false, target: `browserslist:${browserBaseline.join(", ")}`,
    output: {
      path: directory, publicPath: "/", clean: true, filename: "assets/[name]-[contenthash:12].js",
      chunkFilename: "assets/[name]-[contenthash:12].js", cssFilename: "assets/[name]-[contenthash:12].css",
      cssChunkFilename: "assets/[name]-[contenthash:12].css", assetModuleFilename: "assets/[name]-[contenthash:12][ext]",
    },
    module: { rules: [
      { test: /\.jsx$/, use: { loader: "builtin:swc-loader", options: { jsc: {
        parser: { syntax: "ecmascript", jsx: true }, transform: { react: { runtime: "classic" } },
      } } } },
      { test: /\.css$/, type: "css" },
      // Small UI icons used repeatedly across full-page auth navigations were
      // inlined by the previous build. Keep those network requests off the path.
      { test: /\.svg$/, type: "asset", parser: { dataUrlCondition: { maxSize: 4095 } } },
      { test: /\.glb$/, type: "asset/resource" },
    ] },
    plugins: [
      new rspack.DefinePlugin({ "import.meta.env": JSON.stringify(buildEnv) }),
      new rspack.HtmlRspackPlugin({ ...html, scriptLoading: "defer" }),
    ],
    // Preserve the logical name of each separately fallible view and chart.
    optimization: { splitChunks: false, minimizer: [
      new rspack.SwcJsMinimizerRspackPlugin(),
      new rspack.LightningCssMinimizerRspackPlugin({ minimizerOptions: { targets: browserBaseline } }),
    ] },
    performance: { hints: false }, // The measured initial and chart budgets run in checks/plotly-bundle.mjs.
  });
}

export function checkedStats(error, stats) {
  if (error) throw error;
  if (stats.hasErrors()) throw new Error(stats.toString({ all: false, errors: true }));
  return stats;
}

export async function compile(options) {
  const compiler = makeCompiler(options);
  try {
    return await new Promise((resolve, reject) => compiler.run((error, stats) => {
      try { resolve(checkedStats(error, stats)); } catch (failure) { reject(failure); }
    }));
  } finally {
    await new Promise((resolve, reject) => compiler.close(error => error ? reject(error) : resolve()));
  }
}

export function deliveryManifest(stats) {
  const { chunks, entrypoints } = stats.toJson({ all: false, ids: true, chunks: true, chunkRelations: true, entrypoints: true });
  const entries = Object.values(entrypoints);
  assert.equal(entries.length, 1);
  assert.equal(entries[0].chunks.length, 1, "expected_single_initial_chunk");
  return Object.fromEntries(chunks.map(chunk => {
    const scripts = chunk.files.filter(name => name.endsWith(".js"));
    assert.equal(scripts.length, 1, "expected_one_script_per_chunk");
    return [String(chunk.id), {
      file: scripts[0], css: chunk.files.filter(name => name.endsWith(".css")),
      isEntry: entries[0].chunks.includes(chunk.id), dynamicImports: chunk.children.map(String),
    }];
  }));
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  assert.ok(args.length === 0 || (args.length === 1 && args[0] === "--manifest"), "unsupported_build_arguments");
  const stats = await compile();
  if (args.length) {
    await mkdir(path.join(dist, ".aqua"), { recursive: true });
    await writeFile(path.join(dist, ".aqua/manifest.json"), JSON.stringify(deliveryManifest(stats)));
  }
}
