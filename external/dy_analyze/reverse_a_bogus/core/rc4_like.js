"use strict";

function rc4Like(input, key, options = {}) {
  const data = String(input);
  const keyText = String(key);
  if (!keyText.length) throw new Error("rc4 key must not be empty");

  const box = new Array(256);
  for (let index = 0; index < 256; index += 1) box[options.reverseBox ? 255 - index : index] = index;

  let j = 0;
  for (let index = 0; index < 256; index += 1) {
    const keyCode = keyText.charCodeAt(index % keyText.length);
    j = options.reverseBox ? (j * box[index] + j + keyCode) & 0xff : (j + box[index] + keyCode) & 0xff;
    const swap = box[index];
    box[index] = box[j];
    box[j] = swap;
  }

  let i = 0;
  j = 0;
  let output = "";
  for (let index = 0; index < data.length; index += 1) {
    i = (i + 1) & 0xff;
    j = (j + box[i]) & 0xff;
    const swap = box[i];
    box[i] = box[j];
    box[j] = swap;
    const mask = box[(box[i] + box[j]) & 0xff];
    output += String.fromCharCode((data.charCodeAt(index) ^ mask) & 0xff);
  }
  return output;
}

function rc4ReverseBox(input, key) {
  return rc4Like(input, key, { reverseBox: true });
}

module.exports = {
  rc4Like,
  rc4ReverseBox,
};
