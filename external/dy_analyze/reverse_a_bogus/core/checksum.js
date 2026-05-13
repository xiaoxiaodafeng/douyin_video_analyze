"use strict";

function findGuardByte(bytes, start, sentinel, flags, flagBit) {
  if (flags & flagBit) return sentinel;
  for (let index = start; index < bytes.length; index += 1) {
    if (bytes[index] !== sentinel) return bytes[index] & 0xff;
  }
  return (sentinel + 1) & 0xff;
}

function xorChecksum(bytes) {
  return Array.from(bytes).reduce((total, byte) => total ^ (byte & 0xff), 0);
}

module.exports = {
  findGuardByte,
  xorChecksum,
};
