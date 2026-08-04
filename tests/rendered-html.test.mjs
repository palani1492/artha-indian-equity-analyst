import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render(pathname = "/") {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request(`http://localhost${pathname}`, {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("server-renders the Artha Indian equity research workspace", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>Artha \| Indian Equity Research<\/title>/i);
  assert.match(html, /Artha/);
  assert.match(html, /Indian equity research/);
  assert.match(html, /Research desk/);
  assert.match(html, /Investor memory/);
  assert.match(html, /Sources used/);
  assert.match(html, /REL(IANCE|IANCE Industries)/i);
  assert.match(html, /TCS/);
  assert.match(html, /₹/);
  assert.match(html, /<main\b/i);
  assert.doesNotMatch(html, /aria-label="Primary navigation"/i);
  assert.match(html, /aria-label="Ask Artha"/i);
  assert.doesNotMatch(html, /Your site is taking shape|codex-preview|Building your site/i);
  assert.doesNotMatch(html, /[—–]/);
});

test("server-renders an isolated deterministic demo route", async () => {
  const response = await render("/demo");
  assert.equal(response.status, 200);

  const html = await response.text();
  assert.match(html, /Deterministic demo mode/);
  assert.match(html, /Sample data/);
  assert.match(html, /Sign in with Google/);
});

test("ships real interaction, fallback, and inclusive state handling", async () => {
  const [page, demoPage, client, api, data, globalCss, shellCss, researchCss, contextCss, responsiveCss, layout, packageJson] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/demo/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/ArthaWorkspace.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/artha-api.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/artha-data.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../app/styles/shell.css", import.meta.url), "utf8"),
    readFile(new URL("../app/styles/research.css", import.meta.url), "utf8"),
    readFile(new URL("../app/styles/context.css", import.meta.url), "utf8"),
    readFile(new URL("../app/styles/responsive.css", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
  ]);
  const css = `${globalCss}\n${shellCss}\n${researchCss}\n${contextCss}\n${responsiveCss}`;

  assert.match(page, /ArthaWorkspace/);
  assert.match(demoPage, /<ArthaWorkspace demoMode \/>/);
  assert.match(api, /fetch\(/);
  assert.match(client, /\/api\/v1\/chat/);
  assert.match(client, /\/api\/chat/);
  assert.match(api, /AbortController/);
  assert.match(api, /credentials:\s*"include"/);
  assert.match(api, /\/api\/v1\/auth\/me/);
  assert.match(client, /Sign in with Google/);
  assert.match(client, /demo/i);
  assert.match(client, /aria-live="polite"/);
  assert.match(client, /role="alert"/);
  assert.match(client, /aria-expanded/);
  assert.match(api, /Intl\.NumberFormat\("en-IN"/);
  assert.match(api, /formatGreeting/);
  assert.match(api, /formatRelativeTime/);
  assert.match(client, /updatedAt/);
  assert.match(client, /createdAt/);
  assert.match(client, /publishedAt/);
  assert.match(client, /localStorage/);
  assert.match(css, /prefers-reduced-motion:\s*reduce/);
  assert.match(css, /prefers-color-scheme:\s*dark/);
  assert.match(css, /focus-visible/);
  assert.match(css, /@media\s*\(max-width:\s*767px\)/);
  assert.match(layout, /openGraph/);
  assert.match(layout, /\/og\.png/);
  assert.match(layout, /x-forwarded-host/);
  assert.doesNotMatch(`${page}\n${client}\n${api}\n${data}\n${layout}`, /[—–]/);
  assert.doesNotMatch(layout, /Starter Project|codex-preview|_sites-preview/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
});
