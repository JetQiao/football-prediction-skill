#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const home = homedir();
const state = process.env.FOOTBALL_PREDICT_HOME || join(home, ".football-prediction-skill");
const venv = join(state, "venv");
const pythonInVenv = process.platform === "win32" ? join(venv, "Scripts", "python.exe") : join(venv, "bin", "python");
const args = process.argv.slice(2);
const command = args[0] || "install";

function run(program, parameters, options = {}) {
  const result = spawnSync(program, parameters, { stdio: "inherit", ...options });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}

function systemPython() {
  for (const candidate of process.platform === "win32" ? ["py", "python"] : ["python3", "python"]) {
    const parameters = candidate === "py" ? ["-3", "--version"] : ["--version"];
    const probe = spawnSync(candidate, parameters, { stdio: "ignore" });
    if (probe.status === 0) return { command: candidate, prefix: candidate === "py" ? ["-3"] : [] };
  }
  throw new Error("未找到 Python 3.10+，请先安装 Python。 ");
}

function installRuntime() {
  mkdirSync(state, { recursive: true });
  if (!existsSync(pythonInVenv)) {
    const python = systemPython();
    run(python.command, [...python.prefix, "-m", "venv", venv]);
  }
  run(pythonInVenv, ["-m", "pip", "install", "--disable-pip-version-check", "--upgrade", root]);
}

function skillTargets() {
  const codexHome = process.env.CODEX_HOME || join(home, ".codex");
  return [join(codexHome, "skills", "football-prediction-skill"), join(home, ".claude", "skills", "football-prediction-skill")];
}

function installSkill() {
  const source = join(root, "skill", "football-prediction-skill");
  for (const target of skillTargets()) {
    rmSync(target, { recursive: true, force: true });
    mkdirSync(dirname(target), { recursive: true });
    cpSync(source, target, { recursive: true });
    console.log(`✓ 已安装 Skill：${target}`);
  }
}

try {
  if (command === "install") {
    installRuntime();
    installSkill();
    console.log("✓ 安装完成。可在 Codex / Claude Code 中说：分析今天的竞彩足球并生成报告");
    console.log("  命令行运行：npx -y github:JetQiao/football-prediction-skill daily --date today");
    console.log("  若需全局 football-predict 命令：npm install -g github:JetQiao/football-prediction-skill");
  } else if (command === "uninstall") {
    for (const target of skillTargets()) rmSync(target, { recursive: true, force: true });
    rmSync(state, { recursive: true, force: true });
    console.log("✓ 已卸载 Skill 与本地运行环境（历史报告未存放在 Skill 目录中）");
  } else {
    if (!existsSync(pythonInVenv)) installRuntime();
    const forwarded = command === "demo" ? ["daily", "--demo", ...args.slice(1)] : args;
    run(pythonInVenv, ["-m", "football_prediction", ...forwarded]);
  }
} catch (error) {
  console.error(`错误：${error.message}`);
  process.exit(1);
}
