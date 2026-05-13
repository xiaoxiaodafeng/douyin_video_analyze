"use strict";

const { sm3 } = require("./sm3");
const { DEFAULT_ENV_BYTES, DEFAULT_USER_AGENT, DEFAULT_VERSION, UA_RC4_KEY } = require("./constants");
const { encodeBySelector } = require("./base64_custom");
const { bytesToBinaryString, littleEndianBytes, stringToVmBytes } = require("./bytes");
const { findGuardByte, xorChecksum } = require("./checksum");
const { parseVersionBytes, buildScreenFingerprint } = require("./fingerprint");
const { encodePairMasked } = require("./mask");
const { computeConfirmedStages } = require("./query_stages");
const { rc4ReverseBox } = require("./rc4_like");

function buildPayload96(rawUrl, options = {}) {
  const now = Math.trunc(options.now ?? Date.now());
  const random = options.random || Math.random;
  const queryStages = computeConfirmedStages(rawUrl);
  const versionBytes = parseVersionBytes(options.version || DEFAULT_VERSION);
  const screenBytes = stringToVmBytes(buildScreenFingerprint(options));
  const dynamicTextBytes = stringToVmBytes(`${(now + 3) & 0xff},`);
  const envBytes = options.envBytes || DEFAULT_ENV_BYTES;
  const argByte16 = options.argByte16 ?? 129;
  const argByte17 = options.argByte17 ?? 14;
  const runtimeByte27 = options.runtimeByte27 ?? 6;
  const dayBucket = Math.floor((now - 1721836800000) / 1000 / 60 / 60 / 24 / 14);
  const packetHeader = options.packetHeader || [
    ...encodePairMasked(versionBytes.slice(0, 2), 0, random, options.entropy),
    ...encodePairMasked(versionBytes.slice(0, 2), 2, random, {
      mode2Low: options.mode2Low ?? 110,
      mode2High: options.mode2High ?? 179,
      ...(options.entropy || {}),
    }),
  ];

  const queryHash2 = queryStages.queryHash2;
  const fixedHash2 = queryStages.fixedHash2;
  const uaCipher = rc4ReverseBox(options.userAgent || DEFAULT_USER_AGENT, options.uaKey || UA_RC4_KEY);
  const uaBase64 = encodeBySelector(uaCipher, "s3");
  const uaHash = sm3(uaBase64);
  const shiftedNow = now - 1;
  const nowBytes = littleEndianBytes(now, 6);
  const shiftedNowBytes = littleEndianBytes(shiftedNow, 6);
  const flags = envBytes[4] || 0;
  const aid = Number(options.aid || new URL(rawUrl).searchParams.get("aid") || 6383) || 0;

  const fields = {
    slot24: 41,
    slot26: dayBucket & 0xff,
    slot27: runtimeByte27 & 0xff,
    slot28: (argByte16 - 129 + 3) & 0xff,
    slot29: nowBytes[0],
    slot30: nowBytes[1],
    slot31: nowBytes[2],
    slot32: nowBytes[3],
    slot33: nowBytes[4],
    slot34: nowBytes[5],
    slot35: argByte16 & 0xff,
    slot36: (argByte16 >> 8) & 0xff,
    slot38: envBytes[4] & 0xff,
    slot39: (envBytes[4] >> 8) & 0xff,
    slot40: envBytes[0] & 0xff,
    slot41: envBytes[1] & 0xff,
    slot42: envBytes[2] & 0xff,
    slot43: envBytes[3] & 0xff,
    slot44: argByte17 & 0xff,
    slot45: (argByte17 >> 8) & 0xff,
    slot46: (argByte17 >> 16) & 0xff,
    slot47: (argByte17 >> 24) & 0xff,
    slot48: queryHash2[9],
    slot49: queryHash2[18],
    slot51: findGuardByte(queryHash2, 3, 11, flags, 2),
    slot52: fixedHash2[10],
    slot53: fixedHash2[19],
    slot55: findGuardByte(fixedHash2, 4, 8, flags, 4),
    slot56: uaHash[11],
    slot57: uaHash[21],
    slot59: findGuardByte(uaHash, 5, 12, flags, 8),
    slot60: shiftedNowBytes[0],
    slot61: shiftedNowBytes[1],
    slot62: shiftedNowBytes[2],
    slot63: shiftedNowBytes[3],
    slot64: shiftedNowBytes[4],
    slot65: shiftedNowBytes[5],
    slot66: options.integrityMode ?? 3,
    slot67: 0,
    slot68: 0,
    slot69: 0,
    slot70: 0,
    slot71: aid & 0xff,
    slot72: (aid >> 8) & 0xff,
    slot73: 0,
    slot74: 0,
    slot79: screenBytes.length & 0xff,
    slot80: (screenBytes.length >> 8) & 0xff,
    slot84: dynamicTextBytes.length & 0xff,
    slot85: (dynamicTextBytes.length >> 8) & 0xff,
  };

  fields.slot87 = xorChecksum([
    ...packetHeader,
    fields.slot24,
    fields.slot26,
    fields.slot27,
    fields.slot28,
    fields.slot29,
    fields.slot30,
    fields.slot31,
    fields.slot32,
    fields.slot33,
    fields.slot34,
    fields.slot35,
    fields.slot36,
    fields.slot38,
    fields.slot39,
    fields.slot40,
    fields.slot41,
    fields.slot42,
    fields.slot43,
    fields.slot44,
    fields.slot45,
    fields.slot46,
    fields.slot47,
    fields.slot48,
    fields.slot49,
    fields.slot51,
    fields.slot52,
    fields.slot53,
    fields.slot55,
    fields.slot56,
    fields.slot57,
    fields.slot59,
    fields.slot60,
    fields.slot61,
    fields.slot62,
    fields.slot63,
    fields.slot64,
    fields.slot65,
    fields.slot66,
    fields.slot67,
    fields.slot68,
    fields.slot69,
    fields.slot70,
    fields.slot71,
    fields.slot72,
    fields.slot73,
    fields.slot74,
    fields.slot79,
    fields.slot80,
    fields.slot84,
    fields.slot85,
  ]);

  const payload = [
    fields.slot34,
    fields.slot44,
    fields.slot56,
    fields.slot61,
    fields.slot73,
    fields.slot29,
    fields.slot70,
    fields.slot45,
    fields.slot35,
    fields.slot49,
    fields.slot38,
    fields.slot66,
    fields.slot51,
    fields.slot68,
    fields.slot28,
    fields.slot48,
    fields.slot64,
    fields.slot47,
    fields.slot30,
    fields.slot71,
    fields.slot26,
    fields.slot55,
    fields.slot31,
    fields.slot69,
    fields.slot59,
    fields.slot40,
    fields.slot62,
    fields.slot63,
    fields.slot27,
    fields.slot72,
    fields.slot41,
    fields.slot74,
    fields.slot57,
    fields.slot52,
    fields.slot42,
    fields.slot39,
    fields.slot33,
    fields.slot67,
    fields.slot53,
    fields.slot43,
    fields.slot65,
    fields.slot46,
    fields.slot36,
    fields.slot24,
    fields.slot60,
    fields.slot32,
    fields.slot79,
    fields.slot80,
    fields.slot84,
    fields.slot85,
    ...screenBytes,
    ...dynamicTextBytes,
    fields.slot87,
  ];

  return {
    payload,
    packetHeader,
    fields,
    screenFingerprint: bytesToBinaryString(screenBytes),
    dynamicText: bytesToBinaryString(dynamicTextBytes),
    uaBase64,
    uaHash,
    queryStages,
  };
}

module.exports = {
  buildPayload96,
};
