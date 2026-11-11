/* Run once in the existing EA Web App's DevTools Console with the v2 observer
 * attached. This invokes one native read. It returns no account data and does
 * not print, export, retain, or collect authentication values.
 */
void (() => {
  "use strict";
  if (location.protocol !== "https:" || !/^(www\.)?ea\.com$/.test(location.hostname) ||
      !/\/ultimate-team\/web-app(?:\/|$)/.test(location.pathname)) return;
  try {
    if (typeof services !== "undefined" && typeof services.User?.requestCurrencies === "function")
      services.User.requestCurrencies();
  } catch { /* An unavailable read must not dump account-bearing error objects. */ }
})();
