import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach } from "vitest";
import { config, tokenStore } from "@/services/api";

if (!process.env.E2E_API) throw new Error("E2E_API is not set: the test backend did not start (see tests/globalSetup.ts).");
configure({ asyncUtilTimeout: 8000 });   // real network + background AI work
config.origin = process.env.E2E_API;   // REST and WebSocket both go to the real server

Element.prototype.scrollIntoView ??= () => {};
window.matchMedia ??= ((q: string) => ({ matches: false, media: q, onchange: null, addEventListener() {}, removeEventListener() {},
  addListener() {}, removeListener() {}, dispatchEvent: () => false })) as unknown as typeof window.matchMedia;

afterEach(() => { cleanup(); tokenStore.clear(); });
