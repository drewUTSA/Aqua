import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { checkedStats, makeCompiler } from "./build.mjs";
import { apiProxy, assetServer, publicAssets } from "./serve.mjs";

const directory = await mkdtemp(path.join(tmpdir(), "aqua-dev-"));
let files = new Map();
const clients = new Set();
const server = assetServer({ files: () => files, proxy: apiProxy, onReload(req, res) {
  if (clients.size >= 32) { res.writeHead(503); res.end(); return; }
  res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-store" });
  res.write(": connected\n\n"); clients.add(res);
  res.on("close", () => clients.delete(res));
} });
const compiler = makeCompiler({ directory, dev: true });
let publication = Promise.resolve();
const watcher = compiler.watch({}, (error, stats) => {
  publication = publication.then(async () => {
    const assets = await publicAssets(checkedStats(error, stats), directory);
    const html = assets.get("/index.html").toString().replace("</body>", '<script src="/__aqua_reload.js" defer></script></body>');
    assets.set("/index.html", Buffer.from(html));
    assets.set("/__aqua_reload.js", Buffer.from("new EventSource('/__aqua_reload').onmessage = () => location.reload();"));
    files = assets;
    for (const client of clients) client.write("data: updated\n\n");
    console.info("Aqua development build ready at http://localhost:5173");
  }).catch(failure => { console.error(failure.message); });
});

let closing;
function stop() {
  closing ||= (async () => {
    for (const client of clients) client.end();
    server.closeAllConnections();
    if (server.listening) await new Promise(resolve => server.close(resolve));
    await new Promise((resolve, reject) => watcher.close(error => error ? reject(error) : resolve()));
    await publication;
    await new Promise((resolve, reject) => compiler.close(error => error ? reject(error) : resolve()));
    await rm(directory, { recursive: true, force: true });
  })();
  return closing;
}
process.once("SIGINT", stop);
process.once("SIGTERM", stop);
server.once("error", async error => { process.exitCode = 1; console.error(error.message); await stop(); });
server.listen(5173, "0.0.0.0");
