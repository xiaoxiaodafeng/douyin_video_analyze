"use strict";

const { encodePairMasked } = require("./mask");
const { buildPayload96 } = require("./payload");
const { finalizeABogus } = require("./finalize");
const { stripKnownSignatureParams } = require("./url_helpers");

function generateABogusPure(rawUrl, options = {}) {
  const random = options.random || Math.random;
  const payloadInfo = buildPayload96(rawUrl, { ...options, random });
  const prefixBytes = encodePairMasked([3, 82], 1, random, options.entropy);
  const aBogus = finalizeABogus(payloadInfo.payload, {
    ...options,
    random,
    packetHeader: payloadInfo.packetHeader,
    prefixBytes,
  });
  return {
    complete: true,
    aBogus,
    payload: payloadInfo.payload,
    packetHeader: payloadInfo.packetHeader,
    prefixBytes,
    fields: payloadInfo.fields,
  };
}

function signUrl(rawUrl, options = {}) {
  const signed = generateABogusPure(rawUrl, options);
  const url = stripKnownSignatureParams(rawUrl);
  url.searchParams.set("a_bogus", signed.aBogus);
  return {
    aBogus: signed.aBogus,
    signedUrl: url.href,
  };
}

module.exports = {
  generateABogusPure,
  signUrl,
};
