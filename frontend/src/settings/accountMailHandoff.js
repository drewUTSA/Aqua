import { accountOwner } from "./accountContract.js";
import { mailToken } from "./accountIdentityContract.js";
export const ACCOUNT_MAIL_PURPOSES = Object.freeze(["password_add", "email_change_new", "email_change_old"]);
// A pasted URL is parsed locally and never fetched. Only the initiating live
// action can provide the matching public request UUID and configured origin.
export function parseAccountMailLink(value, { origin, purpose, requestId }) {
  if (!ACCOUNT_MAIL_PURPOSES.includes(purpose) || typeof value !== "string" || value.length > 2048 || /[\s\p{C}]/u.test(value)) throw Error("account_mail_link_invalid");
  accountOwner(requestId);
  if(!value.startsWith(origin+"/account-action/"+purpose+"#"))throw Error("account_mail_link_invalid");
  const configured = new URL(origin), url = new URL(value);
  if (configured.origin !== origin || !["https:", "http:"].includes(configured.protocol) || url.origin !== origin || url.username || url.password
    || url.pathname !== "/account-action/" + purpose || url.search) throw Error("account_mail_link_invalid");
  const match = /^#request=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})&token=([A-Za-z0-9_-]{43})$/.exec(url.hash);
  if (!match || match[1] !== requestId) throw Error("account_mail_link_invalid");
  return mailToken(match[2]);
}
