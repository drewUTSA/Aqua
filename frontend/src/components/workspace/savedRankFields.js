import { rankLabel } from "./rankGroupsDraft.js";

// Recognize only a complete, single-table ranking that the existing form can
// express. A filter, join or second score would change the population or order.
const id = String.raw`(?:"[a-z][a-z0-9_]{0,62}"|[a-z][a-z0-9_]{0,62})`;
const column = String.raw`${id}(?:\s*\.\s*${id})?`;
const aggregate = String.raw`(?:COUNT\s*\(\s*\*\s*\)|SUM\s*\(\s*${column}\s*\))`;
const query = new RegExp([
  String.raw`^SELECT\s+(?<key>${column})(?:\s+AS\s+(?<keyLabel>${id}))?\s*,\s*`,
  String.raw`(?<metric>${aggregate})(?:\s+AS\s+(?<scoreLabel>${id}))?\s+`,
  String.raw`FROM\s+(?<relation>${column})(?:\s+(?:AS\s+)?(?<alias>${id}))?\s+`,
  String.raw`GROUP\s+BY\s+(?<group>${column}|1)\s+`,
  String.raw`ORDER\s+BY\s+(?<score>${aggregate}|${id}|2)(?:\s+(?<direction>ASC|DESC))?\s+`,
  String.raw`(?:LIMIT\s+(?<limit>[1-9][0-9]{0,2})|FETCH\s+(?:FIRST|NEXT)\s+(?<fetch>[1-9][0-9]{0,2})\s+ROWS?\s+(?:ONLY|WITH\s+TIES))\s*;?$`,
].join(""), "i");

const smallNumbers = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"];
const number = String.raw`(?:[0-9]+|${smallNumbers.join("|")})`;
const cutoff = new RegExp(
  String.raw`\b(top|bottom|highest|lowest)\s+(${number})\b|\b(${number})\s+(highest|lowest|largest|smallest|most|fewest)\b`, "gi",
);
const compoundBefore = /(?:[\d.,/-]|\b(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|and|or|to)\s+|\d+\s+)$/i;
const compoundAfter = /^(?:[.,]\d|\s*(?:[%/–-]|percent\b|per\s+cent\b|hundred\b|thousand\b|million\b|dozen\b|and\s+a\s+half\b|(?:to|or)\s+(?:\d|one\b|two\b|three\b|four\b|five\b|six\b|seven\b|eight\b|nine\b|ten\b)))/i;

function matchingCutoff(question, count, direction) {
  // An executed LIMIT can come from the model or Aqua's result cap. Copy a
  // number only when the employee explicitly asked for that same cutoff.
  const mentions = Array.from(question.toLowerCase().matchAll(cutoff));
  return mentions.length > 0 && mentions.every(match => {
    if (match[1] && compoundAfter.test(question.slice(match.index + match[0].length))) return false;
    if (match[3] && compoundBefore.test(question.slice(0, match.index))) return false;
    const value = match[2] || match[3];
    const rows = /^\d+$/.test(value) ? Number(value) : smallNumbers.indexOf(value) + 1;
    const order = ["top", "highest", "largest", "most"].includes(match[1] || match[4]) ? "top" : "bottom";
    return rows === Number(count) && order === direction;
  });
}

function name(token) {
  return token?.replaceAll('"', "").replace(/\s/g, "").toLowerCase();
}

function field(reference, qualifier) {
  const parts = name(reference).split(".");
  if (parts.length === 2 && parts[0] !== qualifier) return "";
  return rankLabel(parts.at(-1));
}

export function savedRankFields(sql, question) {
  if (typeof sql !== "string" || sql.length > 4096 || typeof question !== "string" || question.length > 2000) return null;
  // The form resolves lowercase physical identifiers. A quoted mixed-case name
  // refers to a different PostgreSQL object and cannot be normalized for it.
  if (Array.from(sql.matchAll(/"([^"]*)"/g)).some(match => match[1] !== match[1].toLowerCase())) return null;
  const terms = query.exec(sql.trim())?.groups;
  if (!terms) return null;
  const count = terms.limit || terms.fetch;
  const direction = terms.direction?.toLowerCase() === "desc" ? "top" : "bottom";
  if (!matchingCutoff(question, count, direction)) return null;
  const relation = name(terms.relation).split(".");
  if (relation.length === 2 && relation[0] !== "public") return null;
  const source = rankLabel(relation.at(-1));
  const qualifier = name(terms.alias) || source;
  const group = field(terms.key, qualifier);
  if (!source || !group || (terms.group !== "1" && field(terms.group, qualifier) !== group)) return null;
  const metric = name(terms.metric);
  const measure = metric === "count(*)" ? "count" : "total";
  const amount = measure === "total" ? field(metric.slice(4, -1), qualifier) : "";
  if (measure === "total" && (!amount || amount === group)) return null;
  const score = name(terms.score), label = name(terms.scoreLabel);
  if (label && label === (name(terms.keyLabel) || group)) return null;
  if (score !== "2" && score !== label && score !== metric) return null;
  return { source, group, measure, field: amount, direction, number: count, ties: "" };
}
