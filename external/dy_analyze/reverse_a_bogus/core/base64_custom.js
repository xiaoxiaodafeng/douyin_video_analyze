"use strict";

const {
  STANDARD_BASE64_ALPHABET,
  INTERMEDIATE_BASE64_ALPHABET,
  FINAL_BASE64_ALPHABET,
} = require("./constants");
const { binaryStringToBytes } = require("./bytes");

function customBase64Encode(bytes, alphabet = FINAL_BASE64_ALPHABET) {
  if (!alphabet || alphabet.length !== 64) throw new Error("custom base64 alphabet must contain 64 characters");
  const input = Array.from(bytes);
  let output = "";

  for (let index = 0; index < input.length; index += 3) {
    const b1 = input[index] & 0xff;
    const b2 = index + 1 < input.length ? input[index + 1] & 0xff : 0;
    const b3 = index + 2 < input.length ? input[index + 2] & 0xff : 0;
    const packed = (b1 << 16) | (b2 << 8) | b3;
    output += alphabet[(packed >>> 18) & 0x3f];
    output += alphabet[(packed >>> 12) & 0x3f];
    output += index + 1 < input.length ? alphabet[(packed >>> 6) & 0x3f] : "=";
    output += index + 2 < input.length ? alphabet[packed & 0x3f] : "=";
  }

  return output;
}

function selectorAlphabet(selector) {
  if (selector === "s3") return INTERMEDIATE_BASE64_ALPHABET;
  if (selector === "s4") return FINAL_BASE64_ALPHABET;
  if (selector === "s0") return STANDARD_BASE64_ALPHABET;
  if (selector === "s1") return "Dkdpgh4ZKsQB80/Mfvw36XI1R25+WUAlEi7NLboqYTOPuzmFjJnryx9HVGcaStCe";
  if (selector === "s2") return "Dkdpgh4ZKsQB80/Mfvw36XI1R25-WUAlEi7NLboqYTOPuzmFjJnryx9HVGcaStCe";
  throw new Error(`unknown base64 selector: ${selector}`);
}

function encodeBySelector(input, selector) {
  const bytes = typeof input === "string" ? binaryStringToBytes(input) : input;
  return customBase64Encode(bytes, selectorAlphabet(selector));
}

module.exports = {
  customBase64Encode,
  selectorAlphabet,
  encodeBySelector,
};
