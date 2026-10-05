/*!
 * ga-cid-to-luma.js
 *
 * Carries the visitor's GA4 client_id into Luma (or any registration platform
 * that stores utm_source) by rewriting links and embeds on the page.
 *
 *   utm_source=<original utm_source>__cid.<client_id>
 *
 * - Reads the `_ga` cookie, e.g. GA1.1.1234567890.1700000000
 *   -> client_id 1234567890.1700000000
 * - Rewrites <a> and <iframe> elements that point at lu.ma / luma.com
 *   (including the checkout button, which is an <a> with an href).
 * - Keeps whatever utm_source the link already has, else the landing page's
 *   utm_source, else "direct". Copies the landing page's other utm_* params
 *   onto the link if the link does not already set them.
 * - Idempotent: a link that already carries a cid is left alone.
 * - No-op if there is no _ga cookie (consent not given, GA blocked, etc.).
 * - Dependency-free. Contains no tracking IDs.
 *
 * Usage: load it after your GA4 tag, on the page that has the Luma embed.
 *   <script src="/js/ga-cid-to-luma.js" defer></script>
 *
 * To test: open the page with ?utm_source=test, click through to Luma, and
 * check the registration's utm_source ends with __cid.<digits>.<digits>.
 */
(function (root) {
  'use strict';

  var UTM_KEYS = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content'];
  var CID_RE = /(?:^|_)cid\.\d+\.\d+(?![\d.])/;

  // _ga cookie format: GA1.<domain depth>.<random>.<first-visit timestamp>
  function clientIdFromCookie(cookieString) {
    var m = /(?:^|;\s*)_ga=([^;]+)/.exec(cookieString || '');
    if (!m) return null;
    var parts = decodeURIComponent(m[1]).split('.');
    if (parts.length < 4) return null;
    var id = parts[2] + '.' + parts[3];
    return /^\d+\.\d+$/.test(id) ? id : null;
  }

  function hasCid(value) {
    return CID_RE.test(value || '');
  }

  function isLumaHost(hostname) {
    var h = (hostname || '').toLowerCase();
    return h === 'lu.ma' || /\.lu\.ma$/.test(h) || h === 'luma.com' || /\.luma\.com$/.test(h);
  }

  function buildSource(existing, landingSource, cid) {
    var base = (existing || landingSource || 'direct').trim() || 'direct';
    return hasCid(base) ? base : base + '__cid.' + cid;
  }

  // Returns the rewritten URL string, or the original string if nothing to do.
  function rewriteUrl(href, cid, landing, baseUrl) {
    var u;
    try {
      u = new URL(href, baseUrl || 'https://example.com/');
    } catch (e) {
      return href;
    }
    if (!isLumaHost(u.hostname)) return href;
    if (hasCid(u.searchParams.get('utm_source'))) return href;

    landing = landing || {};
    u.searchParams.set(
      'utm_source',
      buildSource(u.searchParams.get('utm_source'), landing.utm_source, cid)
    );
    UTM_KEYS.slice(1).forEach(function (k) {
      if (landing[k] && !u.searchParams.has(k)) u.searchParams.set(k, landing[k]);
    });
    return u.toString();
  }

  function landingUtms(search, storage) {
    var out = {};
    var params = new URLSearchParams(search || '');
    UTM_KEYS.forEach(function (k) {
      if (params.get(k)) out[k] = params.get(k);
    });
    // Remember the first landing UTMs for the rest of the visit (best effort).
    try {
      if (Object.keys(out).length && storage) {
        storage.setItem('landing_utms', JSON.stringify(out));
      } else if (storage && storage.getItem('landing_utms')) {
        out = JSON.parse(storage.getItem('landing_utms')) || {};
      }
    } catch (e) { /* storage blocked: fine */ }
    return out;
  }

  function apply(doc, cid, landing, baseUrl) {
    var changed = 0;
    doc.querySelectorAll('a[href]').forEach(function (a) {
      var next = rewriteUrl(a.getAttribute('href'), cid, landing, baseUrl);
      if (next !== a.getAttribute('href')) { a.setAttribute('href', next); changed++; }
    });
    doc.querySelectorAll('iframe[src]').forEach(function (f) {
      var next = rewriteUrl(f.getAttribute('src'), cid, landing, baseUrl);
      if (next !== f.getAttribute('src')) { f.setAttribute('src', next); changed++; }
    });
    return changed;
  }

  function init() {
    var doc = root.document;
    var landing;
    try { landing = landingUtms(root.location.search, root.sessionStorage); }
    catch (e) { landing = landingUtms(root.location.search, null); }

    // The GA tag may set _ga after this script runs, so retry for ~10 seconds.
    var tries = 0;
    (function attempt() {
      var cid = clientIdFromCookie(doc.cookie);
      if (!cid) {
        if (++tries < 20) setTimeout(attempt, 500);
        return; // no cookie: do nothing
      }
      apply(doc, cid, landing, root.location.href);

      // Catch embeds/buttons that are added to the page later.
      if (root.MutationObserver) {
        new root.MutationObserver(function () {
          apply(doc, cid, landing, root.location.href);
        }).observe(doc.body, { childList: true, subtree: true });
      }
    })();
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { clientIdFromCookie: clientIdFromCookie, hasCid: hasCid, isLumaHost: isLumaHost,
                       buildSource: buildSource, rewriteUrl: rewriteUrl, landingUtms: landingUtms };
  }
  if (root.document) {
    if (root.document.readyState === 'loading') {
      root.document.addEventListener('DOMContentLoaded', init);
    } else {
      init();
    }
  }
})(typeof window !== 'undefined' ? window : this);
