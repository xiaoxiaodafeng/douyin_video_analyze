"use strict";

function binaryStringToBytes(value) {
  return Array.prototype.map.call(String(value), (char) => char.charCodeAt(0) & 0xff);
}

function bytesToBinaryString(bytes) {
  return Array.from(bytes, (byte) => String.fromCharCode(byte & 0xff)).join("");
}

function stringToVmBytes(value) {
  const output = [];
  for (const char of String(value)) {
    const code = char.charCodeAt(0);
    if (code & 0xff00) {
      output.push((code >> 8) & 0xff, code & 0xff);
    } else {
      output.push(code & 0xff);
    }
  }
  return output;
}

function littleEndianBytes(value, length) {
  const bytes = [];
  let current = Math.trunc(Number(value) || 0);
  for (let index = 0; index < length; index += 1) {
    bytes.push(current & 0xff);
    current = Math.floor(current / 256);
  }
  return bytes;
}

module.exports = {
  binaryStringToBytes,
  bytesToBinaryString,
  stringToVmBytes,
  littleEndianBytes,
};
