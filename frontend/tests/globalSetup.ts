/** Starts the real backend once for the whole test run (see backend/tests/e2e_server.py). */
import { type ChildProcess, spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const freePort = () => new Promise<number>((resolve, reject) => {
  const s = createServer();
  s.on("error", reject);
  s.listen(0, "127.0.0.1", () => { const { port } = s.address() as { port: number }; s.close(() => resolve(port)); });
});

let child: ChildProcess | undefined;
let dir = "";

export async function setup() {
  const backend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../backend");
  const [port, tg] = [await freePort(), await freePort()];
  dir = mkdtempSync(path.join(tmpdir(), "wayfare-e2e-"));
  // Use the Python that has the backend installed: PYTHON=..\backend\.venv\Scripts\python.exe npm test
  child = spawn(process.env.PYTHON ?? "python", ["tests/e2e_server.py", "--port", String(port), "--tg-port", String(tg), "--db", path.join(dir, "e2e.db")],
    { cwd: backend, stdio: ["ignore", "pipe", "pipe"] });
  let log = "";
  child.stdout?.on("data", (d) => (log += d));
  child.stderr?.on("data", (d) => (log += d));

  const base = `http://127.0.0.1:${port}`;
  const deadline = Date.now() + 60_000;
  for (;;) {
    if (child.exitCode !== null) throw new Error(`The test backend exited before it was ready:\n${log}`);
    try { if ((await fetch(`${base}/api/health`)).ok) break; } catch { /* not up yet */ }
    if (Date.now() > deadline) { child.kill(); throw new Error(`The test backend didn't start within 60s:\n${log}`); }
    await new Promise((r) => setTimeout(r, 250));
  }
  process.env.E2E_API = base;
  process.env.E2E_TG = `http://127.0.0.1:${tg}`;
}

export async function teardown() {
  child?.kill();
  await new Promise((r) => setTimeout(r, 300));
  try { rmSync(dir, { recursive: true, force: true }); } catch { /* the OS may still hold the file; it's a temp dir */ }
}
