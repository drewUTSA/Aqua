const periods = {
  day: /\b(day|daily|today|tomorrow|tonight|yesterday)\b/i,
  month: /\b(month|monthly|january|february|march|april|may|june|july|august|september|october|november|december)\b/i,
  quarter: /\b(quarter|quarterly)\b/i,
  year: /\b(year|annual|annually|yearly)\b/i,
};
const currencyCodes = new Set(Intl.supportedValuesOf?.("currency") || []);
const currencyHint = "Supply the verified USD amounts for both available cash and projected outflows.";
const adjustedHint = "Use final available cash and the full projected outflows for the same period, including any reserves, fees or other adjustments.";
const boundedAmount = /\b(?:at (?:least|most)|(?:no |not )?(?:more|less|greater|fewer) than|up to|approximately|approx|about|around|nearly|roughly|minimum|maximum|range|estimated (?:cash|balance|amount))\b|\b(?:above|below|under|over)\s+(?=usd\b|us dollars?\b|\$|\d)/i;
// Employees assign the two quoted numbers themselves in this form. Accept
// ordinary worksheet language, but never discard an unexplained adjustment.
const worksheetWords = new Set(`
  a an the s i we our my us you they it these those that them this who both all
  in on of to by at as for during over with against versus and while from
  is are was were be been has have had will ll would can could do does should
  how what whether please check calculate tell me show work out want much now
  cash liquidity liquid funds fund available spend on hand worksheet
  ledger close sheet amount amounts figures values sums balance surplus excess
  short shortfall cushion difference gap room headroom exactly equal zero
  projected project projecting projections forecast forecasted estimated estimate
  expected expect outgoing going net outflow outflows disbursements disbursement
  payment payments payable payables needs enough sufficient suffice suffices
  cover covers covering coverage covered compare comparison meet leave leaves
  scenario illustration illustrative business one single same current next last
  period day daily today tomorrow tonight yesterday month monthly quarter quarterly
  year annual annually yearly january february march april may june july august
  september october november december monday tuesday wednesday thursday friday
  saturday sunday dollars dollar usd us desk branch company full note comes
  stands total totals equals see plain reviewed checked verified remaining
`.trim().split(/\s+/));

function plainWorksheet(question) {
  const words = question.toLowerCase()
    .replace(/^(?:(?:the|our|my)\s+)?(?:(?:daily|monthly|quarterly|annual|treasury|cash|liquidity|funding|maturity|branch|desk)\s+){0,3}(?:worksheet|ledger|close sheet)\s+(?:shows|lists|states|records)\s+/, "")
    .replace(/^\p{L}+\s+(?=(?:reviewed|checked|verified)\s+(?:all|these|the)\s+(?:figures|amounts)\b)/u, "")
    .replace(/\b(?:surplus or shortfall|shortfall or (?:surplus|excess)|check if|tell me if)\b/g, " ")
    .replace(/\bu\.s\./g, "us").replace(/['’]s\b/g, "").replace(/\bwe['’]ll\b/g, "we will")
    .replace(/\d[\d,.]*/g, " ").replace(/(?<=[a-z])-(?=[a-z])/g, " ");
  if (/[^\sa-z.,:;!?$]/.test(words)) return false;
  return (words.match(/[a-z]+/g) || []).every(word => worksheetWords.has(word));
}

function explicitDollars(question, match) {
  return /(?:\bUSD|\bUS\$|\bU\.S\.\s*dollars?)\s*$/i.test(question.slice(0, match.index))
    || /^\s*(?:USD|US dollars?|U\.S\. dollars?)\b/i.test(question.slice(match.index + match[0].length));
}

function hasForeignCurrency(question) {
  for (const token of question.matchAll(/(?<![a-z])[a-z]{3}(?![a-z])/gi)) {
    const code = token[0].toUpperCase();
    if (code === "USD" || !currencyCodes.has(code)) continue;
    // In prose, “Bob” can be a name and “all” a quantifier. Beside a figure,
    // the same spelling may identify Bolivian bolivianos or Albanian lek.
    if (token[0] === code
        || /\d(?:\s+in)?\s*$/i.test(question.slice(0, token.index))
        || /^\s*[:=]?\s*\$?\s*\d/.test(question.slice(token.index + token[0].length))) return true;
  }
  return false;
}

// This invitation never assigns a figure to an operand. The employee chooses
// the two quoted amounts after opening the existing scoped calculator.
export function cashContinuation(question) {
  if (typeof question !== "string" || !question.trim() || question.length > 2000) return null;
  const cashSubject = question.replace(/\b(?:cash|liquidity)\s+(?:outflows?|payments?|disbursements?|needs?)\b/gi, "outflows");
  if (!/\b(?:cash|liquidity|liquid funds|funds available|available to (?:cover|meet)|on hand|available funds)\b/i.test(cashSubject)
      || !/\b(?:outflows?|outgoing|going out|payables?|payments?|disbursements?|cash needs?)\b/i.test(question)) return null;
  if (/\b(?:report|snapshot|regulatory|official|filing|LCR|balance sheet|retrieve|lookup|transactions?|approve|authorize|execute|wire|transfer|move funds|send money|post a payment)\b/i.test(question)
      || /(?:^|\b(?:please|can you|could you|go ahead and)\s+)(?:pay|move|send|release)\b/i.test(question)) return null;
  if (!/\d/.test(question)) return null;
  const usd = /\b(?:USD|US dollars?|U\.S\. dollars?)\b|\$/i.test(question);
  if (!usd || !currencyCodes.size || hasForeignCurrency(question) || [...question].some(c => c !== "$" && /\p{Sc}/u.test(c))
      || /%|\b(?:pesos?|euros?|pounds?|yen|yuan|rupees?|francs?|kroner|kronor|Canadian|Australian|exchange rate)\b/i.test(question))
    return { hint: currencyHint };
  // “May we” and “cash may be” do not designate a calendar month.
  const calendar = question.replace(/\bmay\s+(?=we\b|i\b|you\b|it\b|they\b|the\b|be\b|need\b|have\b|not\b|cover\b|fall\b)/gi, "");
  const windows = Object.entries(periods).filter(([,pattern]) => pattern.test(calendar));
  const timeMarkers = new Set(calendar.toLowerCase().match(/\b(?:today|tomorrow|yesterday|monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|april|may|june|july|august|september|october|november|december)\b/g) || []);
  const qualifiers = new Set((question.toLowerCase().match(/\b(?:last|this|next|prior|previous|current)\s+(?:day|month|quarter|year)\b/g) || []));
  if (windows.length !== 1 || timeMarkers.size > 1 || qualifiers.size > 1
      || /\b(?:week|weekly|days|weeks|months|quarters|years|ytd|year.to.date|different periods?|(?:previous|prior|next) (?:cycle|period))\b/i.test(question))
    return { hint: "Which single day, month, quarter or year do both cash and forecast outflows cover?" };
  if (boundedAmount.test(question))
    return { hint: "Supply exact USD figures for available cash and projected outflows. A range, estimate or limit cannot determine the exact difference." };
  const unsignedText = question.replace(/(?<=[a-z])-(?=[a-z])/gi, "");
  if (/[+\-−–()]/.test(unsignedText) || /\b(?:unknown|missing|pending|unavailable|awaiting|unsure|estimated elsewhere|million|billion|thousand|cents|negative|minus|overdraft|overdrawn|below zero|in the red)\b/i.test(question)
      || /(?:^|[^\d])\.\d|\b(?:only one|partial total|other account|different account)\b/i.test(question))
    return { hint: "Supply the final available cash and full projected outflows in USD for that same period." };
  const matches = [...question.matchAll(/\d[\d,.]*(?:[a-z]+)?/gi)];
  if (matches.length !== 2) return { hint: "Supply one available cash amount and one projected outflow for the same period." };
  const sharedDollars = /\b(?:both|all) (?:amounts |figures |values |sums )?(?:(?:are in|are|in) )?USD\b|\b(?:USD|US dollar) (?:cash )?(?:worksheet|ledger|figures|amounts|close sheet)\b/i.test(question);
  if (!sharedDollars && !matches.every(match => explicitDollars(question, match))) return { hint: currencyHint };
  const amounts = [];
  for (const match of matches) {
    const literal = match[0].replace(/[.,]$/, "");
    if (!/^(?:0|[1-9]\d*|[1-9]\d{0,2}(?:,\d{3})+)(?:\.\d{1,2})?$/.test(literal)) return null;
    const value = literal.replaceAll(",", "");
    if (value.length > 16 || Number(value) > 1e12) return null;
    amounts.push({ literal, value });
  }
  if (!plainWorksheet(question)) return { hint: adjustedHint };
  return { question, period: windows[0][0], amounts };
}
