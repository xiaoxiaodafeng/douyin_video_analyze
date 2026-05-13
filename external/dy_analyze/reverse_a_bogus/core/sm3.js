"use strict";

function rotl(value, shift) {
  shift %= 32;
  return ((value << shift) | (value >>> (32 - shift))) >>> 0;
}

function tj(index) {
  if (index >= 0 && index < 16) return 0x79cc4519;
  if (index >= 16 && index < 64) return 0x7a879d8a;
  throw new Error("invalid SM3 round index");
}

function ff(index, x, y, z) {
  if (index >= 0 && index < 16) return (x ^ y ^ z) >>> 0;
  if (index >= 16 && index < 64) return ((x & y) | (x & z) | (y & z)) >>> 0;
  throw new Error("invalid SM3 FF round index");
}

function gg(index, x, y, z) {
  if (index >= 0 && index < 16) return (x ^ y ^ z) >>> 0;
  if (index >= 16 && index < 64) return ((x & y) | (~x & z)) >>> 0;
  throw new Error("invalid SM3 GG round index");
}

function utf8Bytes(text) {
  const raw = encodeURIComponent(text).replace(/%([0-9A-F]{2})/g, (_, hex) =>
    String.fromCharCode(Number.parseInt(hex, 16)),
  );
  const bytes = new Array(raw.length);
  for (let index = 0; index < raw.length; index += 1) {
    bytes[index] = raw.charCodeAt(index);
  }
  return bytes;
}

class SM3 {
  constructor() {
    this.reg = new Array(8);
    this.chunk = [];
    this.size = 0;
    this.reset();
  }

  reset() {
    this.reg[0] = 0x7380166f;
    this.reg[1] = 0x4914b2b9;
    this.reg[2] = 0x172442d7;
    this.reg[3] = 0xda8a0600;
    this.reg[4] = 0xa96f30bc;
    this.reg[5] = 0x163138aa;
    this.reg[6] = 0xe38dee4d;
    this.reg[7] = 0xb0fb0e4e;
    this.chunk = [];
    this.size = 0;
  }

  write(input) {
    const bytes = typeof input === "string" ? utf8Bytes(input) : Array.from(input);
    this.size += bytes.length;

    let chunkRoom = 64 - this.chunk.length;
    if (bytes.length < chunkRoom) {
      this.chunk = this.chunk.concat(bytes);
      return;
    }

    this.chunk = this.chunk.concat(bytes.slice(0, chunkRoom));
    while (this.chunk.length >= 64) {
      this.compress(this.chunk);
      this.chunk = chunkRoom < bytes.length ? bytes.slice(chunkRoom, Math.min(chunkRoom + 64, bytes.length)) : [];
      chunkRoom += 64;
    }
  }

  sum(input, format) {
    if (input !== undefined) {
      this.reset();
      this.write(input);
    }

    this.fill();
    for (let index = 0; index < this.chunk.length; index += 64) {
      this.compress(this.chunk.slice(index, index + 64));
    }

    let output;
    if (format === "hex") {
      output = "";
      for (let index = 0; index < 8; index += 1) {
        output += this.reg[index].toString(16).padStart(8, "0");
      }
    } else {
      output = new Array(32);
      for (let index = 0; index < 8; index += 1) {
        let value = this.reg[index];
        output[4 * index + 3] = (value & 0xff) >>> 0;
        value >>>= 8;
        output[4 * index + 2] = (value & 0xff) >>> 0;
        value >>>= 8;
        output[4 * index + 1] = (value & 0xff) >>> 0;
        value >>>= 8;
        output[4 * index] = (value & 0xff) >>> 0;
      }
    }

    this.reset();
    return output;
  }

  compress(block) {
    if (block.length < 64) throw new Error("SM3 block is shorter than 64 bytes");

    const words = new Array(132);
    for (let index = 0; index < 16; index += 1) {
      words[index] = block[4 * index] << 24;
      words[index] |= block[4 * index + 1] << 16;
      words[index] |= block[4 * index + 2] << 8;
      words[index] |= block[4 * index + 3];
      words[index] >>>= 0;
    }

    for (let index = 16; index < 68; index += 1) {
      let value = words[index - 16] ^ words[index - 9] ^ rotl(words[index - 3], 15);
      value = value ^ rotl(value, 15) ^ rotl(value, 23);
      words[index] = (value ^ rotl(words[index - 13], 7) ^ words[index - 6]) >>> 0;
    }

    for (let index = 0; index < 64; index += 1) {
      words[index + 68] = (words[index] ^ words[index + 4]) >>> 0;
    }

    const state = this.reg.slice(0);
    for (let index = 0; index < 64; index += 1) {
      let ss1 = rotl((rotl(state[0], 12) + state[4] + rotl(tj(index), index)) & 0xffffffff, 7);
      ss1 >>>= 0;
      const ss2 = (ss1 ^ rotl(state[0], 12)) >>> 0;
      let tt1 = ff(index, state[0], state[1], state[2]);
      tt1 = (tt1 + state[3] + ss2 + words[index + 68]) & 0xffffffff;
      let tt2 = gg(index, state[4], state[5], state[6]);
      tt2 = (tt2 + state[7] + ss1 + words[index]) & 0xffffffff;

      state[3] = state[2];
      state[2] = rotl(state[1], 9);
      state[1] = state[0];
      state[0] = tt1 >>> 0;
      state[7] = state[6];
      state[6] = rotl(state[5], 19);
      state[5] = state[4];
      state[4] = (tt2 ^ rotl(tt2, 9) ^ rotl(tt2, 17)) >>> 0;
    }

    for (let index = 0; index < 8; index += 1) {
      this.reg[index] = (this.reg[index] ^ state[index]) >>> 0;
    }
  }

  fill() {
    const bitLength = 8 * this.size;
    let remainder = this.chunk.push(0x80) % 64;
    if (64 - remainder < 8) remainder -= 64;
    for (; remainder < 56; remainder += 1) this.chunk.push(0);
    for (let index = 0; index < 4; index += 1) {
      const high = Math.floor(bitLength / 0x100000000);
      this.chunk.push((high >>> (8 * (3 - index))) & 0xff);
    }
    for (let index = 0; index < 4; index += 1) {
      this.chunk.push((bitLength >>> (8 * (3 - index))) & 0xff);
    }
  }
}

function sm3(input, format) {
  return new SM3().sum(input, format);
}

module.exports = {
  SM3,
  sm3,
};
