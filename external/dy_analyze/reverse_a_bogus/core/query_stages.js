"use strict";

const { sm3 } = require("./sm3");
const { buildVmQuery } = require("./url_helpers");

function computeConfirmedStages(rawUrl) {
  const query = buildVmQuery(rawUrl);
  const querySalt = "dhzx";
  const queryInput = `${query}${querySalt}`;
  const queryHash = sm3(queryInput);
  const queryHash2 = sm3(queryHash);
  const fixedHash = sm3(querySalt);
  const fixedHash2 = sm3(fixedHash);

  return {
    query,
    querySalt,
    queryInput,
    queryHash,
    queryHash2,
    fixedInput: querySalt,
    fixedHash,
    fixedHash2,
  };
}

module.exports = {
  computeConfirmedStages,
};
