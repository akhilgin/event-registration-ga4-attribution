// Runs the shared parse cases against the Zapier step, plus checks for the browser script.
// Usage: node tests/test_js.js
const assert = require('assert');
const path = require('path');
const cases = require('./parse_cases.json');
const zap = require(path.join(__dirname, '..', 'handler', 'zapier_code_step.js'));
const embed = require(path.join(__dirname, '..', 'embed', 'ga-cid-to-luma.js'));

let n = 0;
for (const c of cases) {
  const got = zap.parseEncoded(c.input);
  for (const k of ['cid', 'source', 'medium', 'campaign', 'term', 'content']) {
    if (k in c) assert.strictEqual(got[k], c[k], `${c.name}: ${k}`);
  }
  n++;
}

// Browser script
const CID = '1234567890.1700000000';
assert.strictEqual(embed.clientIdFromCookie('a=b; _ga=GA1.1.1234567890.1700000000; c=d'), CID);
assert.strictEqual(embed.clientIdFromCookie('GA1.1.123'), null);
assert.strictEqual(embed.clientIdFromCookie('_ga=GA1.1.abc.def'), null);
assert.strictEqual(embed.clientIdFromCookie(''), null);

// Rewrites a Luma link, keeps the landing source, copies other UTMs
let out = new URL(embed.rewriteUrl('https://lu.ma/example-event', CID,
  { utm_source: 'newsletter', utm_medium: 'email', utm_campaign: 'spring' }));
assert.strictEqual(out.searchParams.get('utm_source'), 'newsletter__cid.' + CID);
assert.strictEqual(out.searchParams.get('utm_medium'), 'email');
assert.strictEqual(out.searchParams.get('utm_campaign'), 'spring');

// No source anywhere -> direct
out = new URL(embed.rewriteUrl('https://lu.ma/example-event', CID, {}));
assert.strictEqual(out.searchParams.get('utm_source'), 'direct__cid.' + CID);

// The link's own utm_source wins; its own utm_medium is not overwritten
out = new URL(embed.rewriteUrl('https://lu.ma/e?utm_source=partner&utm_medium=social', CID,
  { utm_source: 'newsletter', utm_medium: 'email' }));
assert.strictEqual(out.searchParams.get('utm_source'), 'partner__cid.' + CID);
assert.strictEqual(out.searchParams.get('utm_medium'), 'social');

// Idempotent
const once = embed.rewriteUrl('https://lu.ma/example-event', CID, {});
assert.strictEqual(embed.rewriteUrl(once, CID, {}), once);

// Non-Luma links are untouched, including look-alike hosts
for (const h of ['https://example.com/x', 'https://notlu.ma/x', 'https://lu.ma.evil.example/x']) {
  assert.strictEqual(embed.rewriteUrl(h, CID, {}), h);
}
// Subdomain and luma.com are handled
assert.ok(embed.rewriteUrl('https://luma.com/e', CID, {}).includes('cid.'));
assert.ok(embed.rewriteUrl('https://embed.lu.ma/e', CID, {}).includes('cid.'));

console.log(`js ok (${n} shared cases + embed checks)`);
