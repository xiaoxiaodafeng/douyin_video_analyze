"use strict";

function stripKnownSignatureParams(rawUrl) {
  const url = new URL(rawUrl);
  url.searchParams.delete("a_bogus");
  url.searchParams.delete("timestamp");
  url.searchParams.delete("x-secsdk-web-signature");
  return url;
}

function buildVmQuery(rawUrl) {
  const url = stripKnownSignatureParams(rawUrl);
  return url.search.startsWith("?") ? url.search.slice(1) : url.search;
}

module.exports = {
  stripKnownSignatureParams,
  buildVmQuery,
};
