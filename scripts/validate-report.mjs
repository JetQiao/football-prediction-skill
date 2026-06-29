#!/usr/bin/env node

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const target = process.argv[2];
if (!target) {
  console.error("用法：node scripts/validate-report.mjs <report.html>");
  process.exit(2);
}

const html = readFileSync(resolve(target), "utf8");
const scripts = [...html.matchAll(/<script(?:[^>]*)>([\s\S]*?)<\/script>/g)].map((match) => match[1]);
if (scripts.length < 2) throw new Error("报告必须包含内联 JSON 与渲染脚本");
JSON.parse(scripts[0]);
new Function(scripts.at(-1));

const externalAssets = [
  ...html.matchAll(/<script[^>]+src=["']https?:/gi),
  ...html.matchAll(/<link[^>]+href=["']https?:/gi),
];
if (externalAssets.length) throw new Error("报告包含外部脚本或样式资源");
if (!html.includes('@media(max-width:560px)')) throw new Error("报告缺少移动端断点");
if (!html.includes('id="matchList"')) throw new Error("报告缺少赛单容器");

console.log("HTML 内联 JSON、JavaScript、离线资源和响应式结构检查通过");
