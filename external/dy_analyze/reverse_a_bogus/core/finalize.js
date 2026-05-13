"use strict";

const { FINAL_PACKET_RC4_KEY } = require("./constants");
const { encodeBySelector } = require("./base64_custom");
const { bytesToBinaryString } = require("./bytes");
const { expandMaskedTriples, encodePairMasked } = require("./mask");
const { rc4ReverseBox } = require("./rc4_like");

function finalizeABogus(payload96, options = {}) {
  const random = options.random || Math.random;
  const entropy = options.entropy || {};
  const header = options.packetHeader || [
    ...encodePairMasked([1, 0], 0, random, entropy),
    ...encodePairMasked([1, 0], 2, random, entropy),
  ];
  const prefix = options.prefixBytes || encodePairMasked([3, 82], 1, random, entropy);
  const body = expandMaskedTriples(payload96, random);
  const packet = bytesToBinaryString([...header, ...body]);
  const encryptedPacket = rc4ReverseBox(packet, options.finalKey || FINAL_PACKET_RC4_KEY);
  return encodeBySelector(bytesToBinaryString(prefix) + encryptedPacket, "s4");
}

module.exports = {
  finalizeABogus,
};
