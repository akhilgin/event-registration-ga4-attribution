// Zapier "Code by Zapier" (JavaScript) step.
//
// Trigger: your registration platform's "new registration" webhook/event.
// Place this step right after the trigger.
//
// Input Data (map these in the Zapier step):
//   encoded          required  the raw utm_source stored on the registration,
//                              e.g. "newsletter__cid.1234567890.1700000000"
//   measurement_id   required  GA4 measurement ID (G-XXXXXXXXXX)
//   api_secret       required  GA4 Measurement Protocol API secret
//   event_name       optional  default "registration"
//   utm_medium, utm_campaign, utm_term, utm_content
//                    optional  explicit values from the platform; these win over
//                              anything parsed out of `encoded`
//   event_ref        optional  free-text label for which event this was
//   debug            optional  "true" -> use GA4's validation endpoint (nothing recorded)
//
// Note: Zapier Code steps have no separate secret store, so api_secret lives in the
// Zap's step configuration. Limit who can edit the Zap. Do not put the secret in
// client-side code or in a repo.
//
// The client_id is found by its "cid." prefix wherever it sits in the string.
// Never split on "__" and take a fixed position.
//
// We deliberately do not send the registrant's email or name to GA4
// (Google's terms prohibit sending PII).

// `cid.<digits>.<digits>` at the start of the string or after an underscore.
const CID_RE = /(?:^|_)cid\.(\d+\.\d+)(?![\d.])/;
const FIELDS = ['source', 'medium', 'campaign', 'term', 'content'];

function parseEncoded(encoded) {
  const result = { cid: null, source: null, medium: null, campaign: null, term: null, content: null };
  if (typeof encoded !== 'string' || !encoded.trim()) return result;
  let text = encoded.trim();

  const m = CID_RE.exec(text);
  if (m) {
    result.cid = m[1];
    text = text.slice(0, m.index) + '__' + text.slice(m.index + m[0].length);
  }

  const tokens = text
    .split(/_{2,}/)
    .map((t) => t.replace(/^[_ ]+|[_ ]+$/g, ''))
    .filter(Boolean);
  FIELDS.forEach((f, i) => {
    if (tokens[i]) result[f] = tokens[i];
  });
  return result;
}

function buildPayload(parsed, eventName, extra) {
  const params = { engagement_time_msec: 1 };
  // Reserved Measurement Protocol names. GA4 ignores utm_source / utm_medium here.
  FIELDS.forEach((f) => {
    if (parsed[f]) params[f] = parsed[f];
  });
  Object.assign(params, extra || {});
  return { client_id: parsed.cid, events: [{ name: eventName, params }] };
}

async function run(inputData) {
  const parsed = parseEncoded(inputData.encoded);
  for (const f of FIELDS.slice(1)) {
    const explicit = inputData['utm_' + f];
    if (explicit) parsed[f] = explicit;
  }

  if (!parsed.cid) {
    // No cid (for example a registration via a direct link that never touched the
    // website). Do not invent one: a made-up client_id creates a phantom GA4 user.
    return { sent: false, reason: 'no cid found; not sending to GA4' };
  }

  const debug = String(inputData.debug || '').toLowerCase() === 'true';
  const base = debug
    ? 'https://www.google-analytics.com/debug/mp/collect'
    : 'https://www.google-analytics.com/mp/collect';
  const url =
    base +
    '?measurement_id=' + encodeURIComponent(inputData.measurement_id) +
    '&api_secret=' + encodeURIComponent(inputData.api_secret);

  const extra = inputData.event_ref ? { event_ref: inputData.event_ref } : {};
  const payload = buildPayload(parsed, inputData.event_name || 'registration', extra);

  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const text = await res.text();

  // The live endpoint returns 204 with no body even for bad payloads.
  // Use debug = true while setting up to see validation messages.
  return {
    sent: !debug && res.ok,
    status: res.status,
    client_id: parsed.cid,
    source: parsed.source,
    medium: parsed.medium,
    campaign: parsed.campaign,
    validation: debug ? text : undefined,
  };
}

if (typeof inputData === 'undefined') {
  // Loaded by a test, not by Zapier.
  module.exports = { parseEncoded, buildPayload, run };
} else {
  // Zapier awaits the returned promise and uses the resolved object as the step output.
  return run(inputData);
}
