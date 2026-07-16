#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import {
  chmodSync,
  cpSync,
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  readlinkSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { homedir } from "node:os";
import { delimiter, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const home = homedir();
const state = process.env.FOOTBALL_PREDICT_HOME || join(home, ".football-prediction-skill");
const venv = join(state, "venv");
const runtime = join(state, "runtime");
const runtimePackage = join(runtime, "football_prediction");
const runtimeEntry = join(runtimePackage, "__main__.py");
const pythonInVenv = process.platform === "win32" ? join(venv, "Scripts", "python.exe") : join(venv, "bin", "python");
const args = process.argv.slice(2);
const command = args[0] || "install";
const runtimeDependencies = [
  "duckdb>=1.3,<2",
  "Jinja2>=3.1,<4",
  "numpy>=1.26,<3",
  "platformdirs>=4.2,<5",
  "scipy>=1.12,<2",
];

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

function dependencyIndexes() {
  return [...new Set([
    process.env.FOOTBALL_PIP_INDEX_URL,
    process.env.PIP_INDEX_URL,
    "https://pypi.org/simple",
    "https://pypi.tuna.tsinghua.edu.cn/simple",
    "https://mirrors.aliyun.com/pypi/simple",
  ].filter(Boolean))];
}

function dependenciesReady() {
  const probe = spawnSync(
    pythonInVenv,
    ["-c", "import duckdb, jinja2, numpy, platformdirs, scipy"],
    { stdio: "ignore" },
  );
  return probe.status === 0;
}

function installDependencies() {
  if (dependenciesReady()) return;
  let lastError = "";
  for (const indexUrl of dependencyIndexes()) {
    console.log(`[INFO] 正在从 ${indexUrl} 安装 Python 运行依赖...`);
    const result = spawnSync(
      pythonInVenv,
      [
        "-m", "pip", "install",
        "--disable-pip-version-check",
        "--prefer-binary",
        "--retries", "2",
        "--timeout", "20",
        "--index-url", indexUrl,
        ...runtimeDependencies,
      ],
      {
        encoding: "utf8",
        env: { ...process.env, PIP_DISABLE_PIP_VERSION_CHECK: "1" },
      },
    );
    if (result.status === 0) {
      if (result.stdout) process.stdout.write(result.stdout);
      return;
    }
    const output = `${result.stdout || ""}\n${result.stderr || ""}`.trim().split("\n");
    lastError = output.slice(-8).join("\n");
    console.warn(`[WARN] ${indexUrl} 不可用，尝试下一个镜像。`);
  }
  throw new Error(
    `Python 依赖安装失败。可设置 FOOTBALL_PIP_INDEX_URL 指向可访问的 PyPI 镜像后重试。\n${lastError}`,
  );
}

function copyRuntimeSource() {
  rmSync(runtimePackage, { recursive: true, force: true });
  mkdirSync(runtime, { recursive: true });
  cpSync(join(root, "src", "football_prediction"), runtimePackage, { recursive: true });
}

function installRuntime() {
  mkdirSync(state, { recursive: true });
  if (!existsSync(pythonInVenv)) {
    const python = systemPython();
    run(python.command, [...python.prefix, "-m", "venv", venv]);
  }
  // 直接复制运行包，避免 pip 为本地项目启动隔离构建并额外下载 setuptools/wheel。
  installDependencies();
  copyRuntimeSource();
}

function runtimeEnvironment() {
  const current = process.env.PYTHONPATH;
  return { ...process.env, PYTHONPATH: current ? `${runtime}${delimiter}${current}` : runtime };
}

function npmExecutable() {
  return process.platform === "win32" ? "npm.cmd" : "npm";
}

function globalCommandPath() {
  const result = spawnSync(npmExecutable(), ["prefix", "--global"], { encoding: "utf8" });
  if (result.status !== 0) return null;
  const prefix = result.stdout.trim();
  return process.platform === "win32" ? join(prefix, "football-predict.cmd") : join(prefix, "bin", "football-predict");
}

function stablePackagePath() {
  return join(state, "package");
}

function ownsGlobalCommand(commandPath) {
  if (!commandPath || !existsSync(commandPath)) return false;
  const stat = lstatSync(commandPath);
  if (stat.isSymbolicLink()) {
    return readlinkSync(commandPath).includes("football-prediction-skill");
  }
  try {
    return readFileSync(commandPath, "utf8").includes("football-prediction-skill launcher");
  } catch {
    return false;
  }
}

function copyStablePackage() {
  const target = stablePackagePath();
  if (resolve(root) === resolve(target)) return target;
  rmSync(target, { recursive: true, force: true });
  mkdirSync(target, { recursive: true });
  for (const name of ["bin", "skill", "src"]) cpSync(join(root, name), join(target, name), { recursive: true });
  cpSync(join(root, "package.json"), join(target, "package.json"));
  chmodSync(join(target, "bin", "skill-cli.mjs"), 0o755);
  return target;
}

function installGlobalCommand() {
  if (process.env.FOOTBALL_SKIP_GLOBAL_INSTALL === "1") return { installed: false, skipped: true, path: null };
  const commandPath = globalCommandPath();
  if (!commandPath) return { installed: false, skipped: false, path: null };
  try {
    const stablePackage = copyStablePackage();
    const stableCli = join(stablePackage, "bin", "skill-cli.mjs");
    mkdirSync(dirname(commandPath), { recursive: true });
    if (existsSync(commandPath)) {
      if (!ownsGlobalCommand(commandPath)) throw new Error(`目标命令已存在且不属于本项目：${commandPath}`);
      rmSync(commandPath, { force: true });
    }
    if (process.platform === "win32") {
      writeFileSync(
        commandPath,
        `@echo off\r\nREM football-prediction-skill launcher\r\nnode "${stableCli}" %*\r\n`,
        "utf8",
      );
    } else {
      symlinkSync(stableCli, commandPath);
    }
    return { installed: true, skipped: false, path: commandPath };
  } catch (error) {
    console.warn(`[WARN] 无法自动注册全局命令，Skill 本身已安装。\n${error.message}`);
    return { installed: false, skipped: false, path: null };
  }
}

function uninstallGlobalCommand() {
  if (process.env.FOOTBALL_SKIP_GLOBAL_INSTALL === "1") return;
  const commandPath = globalCommandPath();
  if (ownsGlobalCommand(commandPath)) rmSync(commandPath, { force: true });
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
    const globalCommand = installGlobalCommand();
    console.log("✓ 安装完成。可在 Codex / Claude Code 中说：分析今天的竞彩足球并生成报告");
    if (globalCommand.installed) {
      console.log(`✓ 已注册全局命令：${globalCommand.path || "football-predict"}`);
      console.log("  命令行运行：football-predict daily --date today");
    } else if (!globalCommand.skipped) {
      console.log("  可继续使用：npx -y github:JetQiao/football-prediction-skill daily --date today");
    }
  } else if (command === "uninstall") {
    for (const target of skillTargets()) rmSync(target, { recursive: true, force: true });
    uninstallGlobalCommand();
    rmSync(state, { recursive: true, force: true });
    console.log("✓ 已卸载 Skill 与本地运行环境（历史报告未存放在 Skill 目录中）");
  } else {
    if (!existsSync(pythonInVenv) || !existsSync(runtimeEntry) || !dependenciesReady()) installRuntime();
    const forwarded = command === "demo" ? ["daily", "--demo", ...args.slice(1)] : args;
    run(pythonInVenv, ["-m", "football_prediction", ...forwarded], { env: runtimeEnvironment() });
  }
} catch (error) {
  console.error(`错误：${error.message}`);
  process.exit(1);
}
