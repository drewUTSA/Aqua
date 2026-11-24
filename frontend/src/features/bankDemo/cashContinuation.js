const periods = {
  day: /\b(day|daily|today|tomorrow|tonight|yesterday)\b/i,
  month: /\b(month|monthly|january|february|march|april|may|june|july|august|september|october|november|december)\b/i,
  quarter: /\b(quarter|quarterly)\b/i,
  year: /\b(year|annual|annually|yearly)\b/i,
};

// This invitation never assigns a figure to an operand. The employee chooses
// the two quoted amounts after opening the existing scoped calculator.
export function cashContinuation(question) {
  if (typeof question !== "string" || !question.trim() || question.length > 2000) return null;
  const cashSubject = question.replace(/\b(?:cash|liquidity)\s+(?:outflows?|payments?|disbursements?|needs?)\b/gi, "outflows");
  if (!/\b(?:cash|liquidity|liquid funds|funds available|available to (?:cover|meet)|on hand|available funds)\b/i.test(cashSubject)
      || !/\b(?:outflows?|outgoing|going out|payables?|payments?|disbursements?|cash needs?)\b/i.test(question)) return null;
  if (/\b(?:report|snapshot|regulatory|official|filing|LCR|balance sheet|retrieve|lookup|transactions?)\b/i.test(question)) return null;
  if (!/\d/.test(question)) return null;
  const usd = /\b(?:USD|US dollars?|U\.S\. dollars?)\b|\$/i.test(question);
  if (!usd || /[€£¥%]|\b(?:CAD|EUR|GBP|MXN|JPY|AUD|NZD|CHF|CNY|pesos?|euros?|pounds?|Canadian|Australian|exchange rate)\b/i.test(question))
    return { hint: "Supply the verified USD amounts for both available cash and projected outflows." };
  // “May we” and “cash may be” do not designate a calendar month.
  const calendar = question.replace(/\bmay\s+(?=we\b|i\b|you\b|it\b|they\b|the\b|be\b|need\b|have\b|not\b|cover\b|fall\b)/gi, "");
  const windows = Object.entries(periods).filter(([,pattern]) => pattern.test(calendar));
  const timeMarkers = new Set(calendar.toLowerCase().match(/\b(?:today|tomorrow|yesterday|january|february|march|april|may|june|july|august|september|october|november|december)\b/g) || []);
  const qualifiers = new Set((question.toLowerCase().match(/\b(?:last|this|next|prior|previous|current)\s+(?:day|month|quarter|year)\b/g) || []));
  if (windows.length !== 1 || timeMarkers.size > 1 || qualifiers.size > 1
      || /\b(?:week|weekly|days|weeks|months|quarters|years|ytd|year.to.date|different periods?)\b/i.test(question))
    return { hint: "Which single day, month, quarter or year do both cash and forecast outflows cover?" };
  const unsignedText = question.replace(/(?<=[a-z])-(?=[a-z])/gi, "");
  if (/[+\-−–()]/.test(unsignedText) || /\b(?:unknown|missing|pending|unavailable|awaiting|unsure|estimated elsewhere|million|billion|thousand|cents|negative|minus|overdraft|overdrawn|below zero|in the red)\b/i.test(question)
      || /(?:^|[^\d])\.\d|\b(?:only one|partial total|other account|different account)\b/i.test(question))
    return { hint: "Supply the full available cash and projected outflows in USD for that same period." };
  const matches = [...question.matchAll(/\d[\d,.]*(?:[a-z]+)?/gi)];
  if (matches.length !== 2) return { hint: "Supply one available cash amount and one projected outflow for the same period." };
  const amounts = [];
  for (const match of matches) {
    const literal = match[0].replace(/[.,]$/, "");
    if (!/^(?:0|[1-9]\d*|[1-9]\d{0,2}(?:,\d{3})+)(?:\.\d{1,2})?$/.test(literal)) return null;
    const value = literal.replaceAll(",", "");
    if (value.length > 16 || Number(value) > 1e12) return null;
    amounts.push({ literal, value });
  }
  return { question, period: windows[0][0], amounts };
}
