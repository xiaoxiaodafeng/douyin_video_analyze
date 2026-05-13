"use strict";

const { DEFAULT_VERSION } = require("./constants");

function parseVersionBytes(version = DEFAULT_VERSION) {
  return String(version)
    .split(".")
    .map((part) => Number(part) || 0);
}

function buildScreenFingerprint(options = {}) {
  const screen = options.screen || {};
  return [
    screen.innerWidth ?? 1904,
    screen.innerHeight ?? 959,
    screen.outerWidth ?? 160,
    screen.outerHeight ?? 28,
    screen.availWidth ?? 1920,
    screen.availHeight ?? 1032,
    screen.width ?? 1920,
    screen.height ?? 1080,
    options.platform || "Win32",
  ].join("|");
}

module.exports = {
  parseVersionBytes,
  buildScreenFingerprint,
};
