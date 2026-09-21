#!/usr/bin/env node

const { spawnSync } = require("node:child_process");
const { existsSync, mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } = require("node:fs");
const { homedir, platform } = require("node:os");
const { join } = require("node:path");

if (!["darwin", "linux"].includes(platform())) {
  console.error("Specgate suporta macOS e Linux.");
  process.exit(1);
}

const python =
  process.env.SPECGATE_BOOTSTRAP_PYTHON ||
  process.env.DEV_DECISION_BOOTSTRAP_PYTHON ||
  "python3";
const root = join(homedir(), ".local", "share", "specgate");
const venv = join(root, "venv");
const runtime = join(venv, "bin", "python");
const statePath = join(root, "current.json");
const version = require("../package.json").version;

function publicClientRoot() {
  const candidates = [join(__dirname, "..", ".."), join(__dirname, "..")];
  for (const candidate of candidates) {
    const file = join(candidate, "pyproject.toml");
    if (!existsSync(file)) continue;
    const text = readFileSync(file, "utf8");
    if (/^name\s*=\s*"specgate-client"/m.test(text)) return candidate;
  }
  return null;
}

const bundledClient = publicClientRoot();
const packageName =
  process.env.SPECGATE_PYTHON_PACKAGE ||
  process.env.DEV_DECISION_PYTHON_PACKAGE ||
  bundledClient ||
  `specgate-client==${version}`;

function run(command, args) {
  const result = spawnSync(command, args, { stdio: "inherit" });
  if (result.error) return { status: 1, message: result.error.message };
  return { status: Number.isInteger(result.status) ? result.status : 1 };
}

function required(command, args) {
  const result = run(command, args);
  if (result.status !== 0) {
    if (result.message) console.error(result.message);
    throw Object.assign(new Error("command failed"), { status: result.status });
  }
}

function prepare(target) {
  required(python, ["-c", "import sys; sys.exit(0 if sys.version_info >= (3,12) else 'Python 3.12 or newer is required.')"]);
  required(python, ["-m", "venv", target]);
  required(join(target, "bin", "python"), [
    "-m", "pip", "install", "--disable-pip-version-check", "--no-input", packageName,
  ]);
}

const cliArgs = process.argv.slice(2).length ? process.argv.slice(2) : ["install"];
const update = cliArgs[0] === "update";
const previousState = existsSync(statePath) ? readFileSync(statePath, "utf8") : null;
const installedVersion = previousState ? JSON.parse(previousState).version : null;

if (existsSync(runtime) && installedVersion !== version && !update) {
  console.error(`Specgate ${installedVersion || "unknown"} is installed; run update explicitly to install ${version}.`);
  process.exit(2);
}

if (!existsSync(runtime) || update) {
  mkdirSync(root, { recursive: true });
  const backup = join(root, "venv.backup");
  if (existsSync(backup)) {
    console.error("A pending backup exists; restore or remove it before updating.");
    process.exit(2);
  }
  let backedUp = false;
  try {
    if (existsSync(venv)) {
      renameSync(venv, backup);
      backedUp = true;
    }
    prepare(venv);
    required(runtime, ["-m", "specgate.public_cli", ...cliArgs]);
    writeFileSync(statePath, `${JSON.stringify({ version })}\n`, { mode: 0o600 });
    rmSync(backup, { recursive: true, force: true });
  } catch (error) {
    rmSync(venv, { recursive: true, force: true });
    if (backedUp && existsSync(backup)) renameSync(backup, venv);
    if (previousState === null) rmSync(statePath, { force: true });
    else writeFileSync(statePath, previousState, { mode: 0o600 });
    process.exit(error.status || 1);
  }
} else {
  const result = run(runtime, ["-m", "specgate.public_cli", ...cliArgs]);
  process.exit(result.status);
}
