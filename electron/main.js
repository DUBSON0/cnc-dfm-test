"use strict";

const { app, BrowserWindow, dialog } = require("electron");
const { spawn, spawnSync } = require("child_process");
const fs = require("fs");
const http = require("http");
const net = require("net");
const path = require("path");

const SMOKE = process.env.DFM_SMOKE === "1";

let backendProc = null;
let mainWindow = null;

// ---------------------------------------------------------------------------
// Paths: dev mode runs from the repo; packaged mode runs from resources.
// ---------------------------------------------------------------------------

function isPackaged() {
  return app.isPackaged;
}

function backendDir() {
  return isPackaged()
    ? path.join(process.resourcesPath, "backend")
    : path.join(__dirname, "..");
}

// ---------------------------------------------------------------------------
// Python resolution: env override → repo venv (dev) → userData venv
// (packaged, created on first run).
// ---------------------------------------------------------------------------

function venvPython(venvDir) {
  return process.platform === "win32"
    ? path.join(venvDir, "Scripts", "python.exe")
    : path.join(venvDir, "bin", "python");
}

function findExistingPython() {
  if (process.env.DFM_PYTHON && fs.existsSync(process.env.DFM_PYTHON)) {
    return process.env.DFM_PYTHON;
  }
  const devVenv = venvPython(path.join(backendDir(), ".venv"));
  if (fs.existsSync(devVenv)) return devVenv;
  const userVenv = venvPython(path.join(app.getPath("userData"), "venv"));
  if (fs.existsSync(userVenv)) return userVenv;
  return null;
}

function findSystemPython() {
  for (const cand of ["python3.12", "python3.13", "python3"]) {
    const probe = spawnSync(cand, ["--version"], { encoding: "utf8" });
    if (probe.status === 0) return cand;
  }
  return null;
}

/** Create a venv in userData and install requirements (first run, packaged). */
async function firstRunSetup(progressWin) {
  const sysPython = findSystemPython();
  if (!sysPython) {
    throw new Error(
      "Python 3.12+ was not found on this system. Install it (e.g. " +
      "`sudo pacman -S python` / `apt install python3`) and relaunch."
    );
  }
  const venvDir = path.join(app.getPath("userData"), "venv");
  const reqs = path.join(backendDir(), "requirements.txt");

  const run = (cmd, args) =>
    new Promise((resolve, reject) => {
      const p = spawn(cmd, args, { stdio: ["ignore", "pipe", "pipe"] });
      let err = "";
      p.stderr.on("data", (d) => (err += d));
      p.on("close", (code) =>
        code === 0 ? resolve() : reject(new Error(`${cmd} failed:\n${err.slice(-2000)}`))
      );
    });

  progressWin.webContents.send?.("status", "Creating Python environment…");
  await run(sysPython, ["-m", "venv", venvDir]);
  await run(venvPython(venvDir), [
    "-m", "pip", "install", "--upgrade", "pip",
  ]);
  await run(venvPython(venvDir), [
    "-m", "pip", "install", "-r", reqs,
  ]);
  return venvPython(venvDir);
}

// ---------------------------------------------------------------------------
// Backend lifecycle
// ---------------------------------------------------------------------------

function freePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.listen(0, "127.0.0.1", () => {
      const port = srv.address().port;
      srv.close(() => resolve(port));
    });
    srv.on("error", reject);
  });
}

function startBackend(python, port) {
  backendProc = spawn(
    python,
    ["-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", String(port)],
    { cwd: backendDir(), stdio: ["ignore", "pipe", "pipe"] }
  );
  backendProc.stdout.on("data", (d) => process.stdout.write(`[backend] ${d}`));
  backendProc.stderr.on("data", (d) => process.stderr.write(`[backend] ${d}`));
  backendProc.on("exit", (code) => {
    backendProc = null;
    // Unexpected death while the app is open → surface it.
    if (mainWindow && !mainWindow.isDestroyed() && code !== 0 && code !== null) {
      dialog.showErrorBox(
        "Analysis engine stopped",
        `The Python backend exited unexpectedly (code ${code}). ` +
        "Check the logs by running the app from a terminal."
      );
    }
  });
}

function waitForBackend(port, timeoutMs = 30000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const poll = () => {
      const req = http.get(
        { host: "127.0.0.1", port, path: "/", timeout: 1000 },
        (res) => {
          res.resume();
          res.statusCode < 500 ? resolve() : retry();
        }
      );
      req.on("error", retry);
      req.on("timeout", () => { req.destroy(); retry(); });
    };
    const retry = () => {
      if (backendProc === null) return reject(new Error("Backend process exited during startup"));
      if (Date.now() - started > timeoutMs) return reject(new Error("Backend startup timed out"));
      setTimeout(poll, 250);
    };
    poll();
  });
}

function stopBackend() {
  if (backendProc) {
    backendProc.kill("SIGTERM");
    backendProc = null;
  }
}

// ---------------------------------------------------------------------------
// Windows
// ---------------------------------------------------------------------------

function createSetupWindow() {
  const win = new BrowserWindow({
    width: 460,
    height: 220,
    resizable: false,
    frame: false,
    show: !SMOKE,
    backgroundColor: "#0d1117",
  });
  win.loadFile(path.join(__dirname, "setup.html"));
  return win;
}

function createMainWindow(port) {
  mainWindow = new BrowserWindow({
    width: 1520,
    height: 980,
    minWidth: 1000,
    minHeight: 640,
    show: !SMOKE,
    backgroundColor: "#0d1117",
    title: "CNC Manufacturability Ranker",
    autoHideMenuBar: true,
  });
  mainWindow.loadURL(`http://127.0.0.1:${port}/`);
  mainWindow.on("closed", () => (mainWindow = null));
}

// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------

app.whenReady().then(async () => {
  try {
    let python = findExistingPython();
    if (!python) {
      const setupWin = createSetupWindow();
      try {
        python = await firstRunSetup(setupWin);
      } finally {
        if (!setupWin.isDestroyed()) setupWin.close();
      }
    }

    const port = await freePort();
    startBackend(python, port);
    await waitForBackend(port);
    createMainWindow(port);

    if (SMOKE) {
      // Headless self-test: confirm the UI actually loaded over HTTP.
      mainWindow.webContents.once("did-finish-load", async () => {
        const title = await mainWindow.webContents.executeJavaScript("document.title");
        const hasDropzone = await mainWindow.webContents.executeJavaScript(
          "!!document.getElementById('dropzone')"
        );
        console.log(`SMOKE_OK title=${JSON.stringify(title)} dropzone=${hasDropzone}`);
        app.quit();
      });
      mainWindow.webContents.once("did-fail-load", (_e, code, desc) => {
        console.error(`SMOKE_FAIL ${code} ${desc}`);
        app.exit(1);
      });
    }
  } catch (err) {
    if (SMOKE) {
      console.error(`SMOKE_FAIL ${err.message}`);
      app.exit(1);
    }
    dialog.showErrorBox("CNC Manufacturability Ranker failed to start", String(err.message || err));
    app.quit();
  }
});

app.on("window-all-closed", () => {
  stopBackend();
  app.quit();
});

app.on("before-quit", stopBackend);
process.on("exit", stopBackend);
