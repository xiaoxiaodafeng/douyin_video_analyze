"use strict";

const constants = require("./core/constants");
const base64 = require("./core/base64_custom");
const bytes = require("./core/bytes");
const checksum = require("./core/checksum");
const fingerprint = require("./core/fingerprint");
const finalizer = require("./core/finalize");
const mask = require("./core/mask");
const payload = require("./core/payload");
const queryStages = require("./core/query_stages");
const rc4 = require("./core/rc4_like");
const signer = require("./core/sign");
const urlHelpers = require("./core/url_helpers");

function getOption(name, fallback) {
  const prefix = `--${name}=`;
  const hit = process.argv.find((arg) => arg.startsWith(prefix));
  return hit ? hit.slice(prefix.length) : fallback;
}

function main() {
  const rawUrl = process.argv.slice(2).find((arg) => !arg.startsWith("--"));
  if (!rawUrl) {
    console.log("Usage:");
    console.log("  node .\\reverse_a_bogus\\pure_a_bogus.js URL");
    process.exitCode = 1;
    return;
  }

  const result = signer.signUrl(rawUrl, {
    userAgent: getOption("ua", constants.DEFAULT_USER_AGENT),
  });
  console.log(JSON.stringify(result, null, 2));
}

if (require.main === module) main();

module.exports = {
  ...constants,
  ...urlHelpers,
  ...queryStages,
  ...base64,
  ...bytes,
  ...rc4,
  ...mask,
  ...fingerprint,
  ...checksum,
  ...payload,
  ...finalizer,
  ...signer,
};
