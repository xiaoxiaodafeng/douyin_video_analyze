"use strict";

function expandMaskedTriples(bytes, random = Math.random) {
  const input = Array.from(bytes, (byte) => byte & 0xff);
  const output = [];
  for (let index = 0; index < input.length; index += 3) {
    if (index + 2 < input.length) {
      const mask = (random() * 1000) & 0xff;
      const a = input[index];
      const b = input[index + 1];
      const c = input[index + 2];
      output.push(
        ((mask & 145) ^ (a & 110)) & 0xff,
        ((mask & 66) ^ (b & 189)) & 0xff,
        ((mask & 44) ^ (c & 211)) & 0xff,
        ((a & 145) ^ (b & 66) ^ (c & 44)) & 0xff,
      );
    } else {
      output.push(input[index]);
      if (input[index + 1] !== undefined) output.push(input[index + 1]);
    }
  }
  return output;
}

function encodePairMasked(pair, mode = 0, random = Math.random, entropy = {}) {
  const input = Array.from(pair, (byte) => byte & 0xff);
  let seed = random() * 65535;
  let low = seed & 0xff;
  let high = (seed >> 8) & 0xff;
  if (mode === 1) high = entropy.mode1Byte !== undefined ? entropy.mode1Byte & 0xff : 0;
  if (mode === 2) {
    low = entropy.mode2Low !== undefined ? entropy.mode2Low & 0xff : 110;
    high = entropy.mode2High !== undefined ? entropy.mode2High & 0xff : 179;
  }
  return [
    ((low & 170) ^ (input[0] & 85)) & 0xff,
    ((low & 85) ^ (input[0] & 170)) & 0xff,
    ((high & 170) ^ (input[1] & 85)) & 0xff,
    ((high & 85) ^ (input[1] & 170)) & 0xff,
  ];
}

module.exports = {
  expandMaskedTriples,
  encodePairMasked,
};
