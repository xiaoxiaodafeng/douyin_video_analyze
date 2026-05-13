"use strict";

const fs = require("fs");
const path = require("path");
const { signUrl, stripKnownSignatureParams } = require("./pure_a_bogus");

const ROOT = path.resolve(__dirname, "..");
const API_PATH = path.join(ROOT, "api.txt");
const COOKIE_PATH = path.join(ROOT, "cookie.txt");
const OUTPUT_PATH = path.join(__dirname, "api_validation_result.json");
const USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36";

function readApiLines() {
  return fs
    .readFileSync(API_PATH, "utf8")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function readCookie() {
  if (process.env.DOUYIN_COOKIE) return process.env.DOUYIN_COOKIE.trim();
  return fs.readFileSync(COOKIE_PATH, "utf8").trim();
}

function summarizeComment(comment) {
  if (!comment) return null;
  return {
    cid: comment.cid,
    text: String(comment.text || "").slice(0, 80),
    user_name: comment.user && comment.user.nickname,
    ip_label: comment.ip_label,
    digg_count: comment.digg_count,
  };
}

function buildTestUrl(rawUrl, kind) {
  const url = stripKnownSignatureParams(rawUrl);
  url.searchParams.set("cursor", "0");
  url.searchParams.set("count", kind === "reply" ? "3" : "10");
  return url.href;
}

async function requestSignedJson(rawUrl, cookie) {
  const signed = signUrl(rawUrl, { userAgent: USER_AGENT });
  const response = await fetch(signed.signedUrl, {
    headers: {
      accept: "application/json, text/plain, */*",
      "accept-language": "en,zh-CN;q=0.9,zh;q=0.8,zh-TW;q=0.7",
      referer: "https://www.douyin.com/",
      "user-agent": USER_AGENT,
      cookie,
    },
  });
  const text = await response.text();
  const contentType = response.headers.get("content-type") || "";
  const result = {
    status: response.status,
    contentType,
    bdturing: response.headers.has("x-vc-bdturing-parameters"),
    aBogusLength: signed.aBogus.length,
  };

  if (!contentType.includes("application/json")) {
    return { ...result, ok: false, preview: text.slice(0, 200) };
  }

  const json = JSON.parse(text);
  return {
    ...result,
    ok: json.status_code === 0,
    status_code: json.status_code,
    has_more: json.has_more,
    cursor: json.cursor,
    comments: Array.isArray(json.comments) ? json.comments.length : null,
    first: summarizeComment(Array.isArray(json.comments) ? json.comments[0] : null),
  };
}

async function main() {
  const [replyUrl, topUrl] = readApiLines();
  const cookie = readCookie();
  const startedAt = new Date().toISOString();

  const result = {
    startedAt,
    signer: "reverse_a_bogus/pure_a_bogus.js",
    topLevel: await requestSignedJson(buildTestUrl(topUrl, "top"), cookie),
    reply: await requestSignedJson(buildTestUrl(replyUrl, "reply"), cookie),
  };

  result.ok = Boolean(result.topLevel.ok && result.reply.ok);
  fs.writeFileSync(OUTPUT_PATH, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  console.log(JSON.stringify(result, null, 2));
  console.log(`saved=${OUTPUT_PATH}`);
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exitCode = 1;
});
