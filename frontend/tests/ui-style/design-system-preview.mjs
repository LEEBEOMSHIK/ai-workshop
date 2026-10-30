// Synthetic preview server only. Browser interaction belongs to the root reviewer.
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const frontend = resolve(here, "../..");
const require = createRequire(resolve(frontend, "package.json"));
const vitestRequire = createRequire(require.resolve("vitest/package.json"));
const { createServer } = await import(pathToFileURL(vitestRequire.resolve("vite")).href);
const navigation = "\0synthetic-next-navigation";
const server = await createServer({
  root: frontend, configFile: false, logLevel: "error",
  resolve: { alias: [{ find: /^next\/link$/, replacement: resolve(here, "link.fixture.tsx") }] },
  oxc: { jsx: { runtime: "automatic" } },
  server: { host: "127.0.0.1", port: Number(process.env.UI_STYLE_PORT ?? 18191), strictPort: true },
  plugins: [{
    name: "independent-synthetic-design-preview",
    resolveId(id) { if (id === "next/navigation") return navigation; },
    load(id) {
      if (id === navigation) return `
        export const useRouter=()=>({push(){},replace(){},refresh(){},back(){},prefetch(){}});
        export const usePathname=()=>'/__design_system__/';
        export const useSearchParams=()=>new URLSearchParams(window.location.search);
        export const useParams=()=>({});`;
    },
    configureServer(instance) {
      instance.middlewares.use(async (req, res, next) => {
        res.setHeader("Cache-Control", "no-store");
        res.setHeader("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; font-src 'self'; frame-src 'self'; object-src 'none'; form-action 'none'; base-uri 'none'");
        if (req.url?.startsWith("/api/")) {
          res.statusCode = 403;
          res.setHeader("Content-Type", "application/json");
          res.end(JSON.stringify({ error: { code: "synthetic_only", message: "Synthetic preview blocks backend requests." } }));
          return;
        }
        if (!req.url?.startsWith("/__design_system__/")) return next();
        res.setHeader("Content-Type", "text/html; charset=utf-8");
        res.end(await instance.transformIndexHtml(req.url, '<!doctype html><html lang="ko"><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>합성 디자인 시스템 QA</title></head><body><div id="root"></div><script type="module" src="/tests/ui-style/design-system.fixture.tsx"></script></body></html>'));
      });
    },
  }],
});
await server.listen();
console.log(`Synthetic preview: http://127.0.0.1:${server.httpServer.address().port}/__design_system__/`);
console.log("No browser launched. No backend proxy. Stop this owned preview with Ctrl+C.");
let closing = false;
async function close() {
  if (closing) return;
  closing = true;
  await server.close();
  process.exit(0);
}
process.on("SIGINT", close);
process.on("SIGTERM", close);
