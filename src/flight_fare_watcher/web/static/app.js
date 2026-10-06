// Shared helpers used by both the search page (search.js) and the watches
// page (watches.js). No build step, no framework - vanilla JS and fetch,
// matching this being a small local single-user tool.

function showStatus(el, message, kind) {
  el.textContent = message;
  el.className = "status " + kind;
  el.hidden = false;
}

function hideStatus(el) {
  el.hidden = true;
}

// Only ever return a resolved http(s) URL. Used before setting any `href`
// that originates from a scraped/parsed value, so a malformed or malicious
// deep link can never become a javascript:/data: URI in the DOM.
function safeHref(url) {
  if (!url) return null;
  try {
    const parsed = new URL(url, window.location.origin);
    if (parsed.protocol === "http:" || parsed.protocol === "https:") {
      return parsed.href;
    }
  } catch (err) {
    // fall through
  }
  return null;
}

function formatDuration(minutes) {
  if (!minutes) return "–";
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h > 0 ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`;
}

function formatStops(stops) {
  if (stops === null || stops === undefined) return "";
  if (stops === 0) return "Nonstop";
  return stops === 1 ? "1 stop" : `${stops} stops`;
}

// Prices round-tripped through SQLite come back as "450.0" / "126.0" (a REAL
// column via Decimal(str(float))) while freshly-scraped prices are already
// clean integers like "126". Normalize both to the same display form rather
// than showing a trailing ".0" only for watched-route prices.
function formatPrice(value) {
  const num = typeof value === "number" ? value : parseFloat(value);
  if (Number.isNaN(num)) return String(value);
  return Number.isInteger(num) ? String(num) : num.toFixed(2);
}

// Intl.NumberFormat knows each currency's real symbol, symbol placement,
// thousands separators, and minor-unit decimal count (0 for JPY, 2 for USD,
// etc.) - far more correct than hand-rolling currency formatting.
function formatMoney(price, currency) {
  const amount = typeof price === "number" ? price : parseFloat(price);
  if (Number.isNaN(amount)) return `${formatPrice(price)} ${currency || "USD"}`;
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: currency || "USD",
    }).format(amount);
  } catch (err) {
    // An unrecognized currency code (shouldn't happen - the server only ever
    // sends codes from currency.py's SUPPORTED_CURRENCIES) falls back
    // gracefully rather than breaking the whole fare card.
    return `${formatPrice(price)} ${currency || "USD"}`;
  }
}

// --- Live currency conversion -------------------------------------------
//
// Every fare provider prices in USD (see currency.py's module docstring).
// This is purely a display conversion: it never touches the price actually
// searched, sorted, or used to create a watch - only what the fare cards
// render. Rates are fetched once per page load (cached here) and reused for
// every currency the user picks, so switching currencies is instant.

const DISPLAY_CURRENCY_STORAGE_KEY = "ffw_display_currency";
// Mirrors currency.py::ZERO_DECIMAL_CURRENCIES - currencies conventionally
// shown with no decimal places.
const ZERO_DECIMAL_CURRENCIES = new Set(["JPY", "KRW", "HUF", "ISK"]);

function getPreferredCurrency() {
  try {
    return localStorage.getItem(DISPLAY_CURRENCY_STORAGE_KEY) || "USD";
  } catch (err) {
    return "USD"; // private browsing / storage blocked - fall back quietly
  }
}

function setPreferredCurrency(code) {
  try {
    localStorage.setItem(DISPLAY_CURRENCY_STORAGE_KEY, code);
  } catch (err) {
    // per-viewer convenience only; losing it just resets to USD next visit
  }
}

async function fetchExchangeRates(base) {
  const response = await fetch(`/api/exchange-rates?base=${encodeURIComponent(base || "USD")}`);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `exchange rate request failed (${response.status})`);
  }
  const data = await response.json();
  // The server sends each rate as a JSON string (it originates from a
  // Decimal and strings round-trip exactly, unlike floats) - parse once here
  // so every caller can just do arithmetic on `rates` without re-parsing.
  const rates = {};
  for (const [code, value] of Object.entries(data.rates || {})) {
    const parsed = parseFloat(value);
    if (!Number.isNaN(parsed)) rates[code] = parsed;
  }
  return { ...data, rates };
}

function roundForDisplay(amount, currency) {
  return ZERO_DECIMAL_CURRENCIES.has(currency) ? Math.round(amount) : Math.round(amount * 100) / 100;
}

// `rates` holds "1 unit of `base` = rates[code] units of code" - the base
// itself has no entry (Frankfurter never rates a currency against itself),
// so look-ups treat a currency equal to `base` as an implicit rate of 1.
function rateFor(currency, rates, base) {
  if (currency === base) return 1;
  const rate = rates && rates[currency];
  return typeof rate === "number" && !Number.isNaN(rate) ? rate : null;
}

// Converts via `base` in both directions rather than assuming
// `nativeCurrency` already *is* `base` - every fare today happens to be
// priced in USD with rates fetched for base=USD, but this stays correct even
// if that ever changes. Mirrors currency.py::convert() on the server.
//
// Returns `null` if either currency's rate is unknown - callers must fall
// back to showing the native amount rather than display nothing or a wrong
// number.
function convertAmount(amountNative, nativeCurrency, displayCurrency, rates, base) {
  if (nativeCurrency === displayCurrency) return amountNative;
  const fromRate = rateFor(nativeCurrency, rates, base);
  const toRate = rateFor(displayCurrency, rates, base);
  if (fromRate === null || toRate === null || fromRate === 0) return null;
  const amountInBase = amountNative / fromRate;
  return roundForDisplay(amountInBase * toRate, displayCurrency);
}

function populateCurrencySelect(selectEl, supportedCurrencies, selectedCode) {
  selectEl.textContent = "";
  for (const [code, name] of Object.entries(supportedCurrencies)) {
    const option = document.createElement("option");
    option.value = code;
    option.textContent = `${code} - ${name}`;
    if (code === selectedCode) option.selected = true;
    selectEl.appendChild(option);
  }
}

const SITE_LABELS = {
  google_flights: "Google Flights",
  amadeus: "Amadeus",
  demo: "Sample data",
};

function siteLabel(site) {
  return SITE_LABELS[site] || site;
}

function debounce(fn, waitMs) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), waitMs);
  };
}

// Wires a text input to a dropdown of /api/airports suggestions, storing the
// chosen IATA code on the input via a data attribute while still showing a
// friendly "City (CODE)" label. Typing a bare 3-letter code works too -
// autocomplete is a convenience, never a requirement to search.
function wireAirportAutocomplete(inputEl, suggestionsEl) {
  let activeIndex = -1;
  let currentItems = [];

  function close() {
    suggestionsEl.hidden = true;
    suggestionsEl.textContent = "";
    activeIndex = -1;
    currentItems = [];
  }

  function choose(item) {
    inputEl.value = item.label;
    inputEl.dataset.code = item.code;
    close();
  }

  function render(items) {
    currentItems = items;
    suggestionsEl.textContent = "";
    if (items.length === 0) {
      close();
      return;
    }
    items.forEach((item, index) => {
      const row = document.createElement("div");
      row.className = "suggestion-row";
      row.setAttribute("role", "option");
      row.textContent = item.label;
      row.addEventListener("mousedown", (event) => {
        event.preventDefault(); // keep focus so 'blur' doesn't fire first
        choose(item);
      });
      if (index === activeIndex) row.classList.add("active");
      suggestionsEl.appendChild(row);
    });
    suggestionsEl.hidden = false;
  }

  const fetchSuggestions = debounce(async (term) => {
    if (!term || term.length < 2) {
      close();
      return;
    }
    try {
      const response = await fetch(`/api/airports?q=${encodeURIComponent(term)}`);
      if (!response.ok) return;
      const results = await response.json();
      // The field may have lost focus (or its value changed again) while
      // this request was in flight - rendering now would pop the dropdown
      // back open after the user already moved on.
      if (document.activeElement !== inputEl) return;
      render(results);
    } catch (err) {
      // Autocomplete failing silently is fine - the field still accepts a
      // typed code.
    }
  }, 150);

  inputEl.addEventListener("input", () => {
    delete inputEl.dataset.code;
    fetchSuggestions(inputEl.value.trim());
  });

  inputEl.addEventListener("keydown", (event) => {
    if (suggestionsEl.hidden || currentItems.length === 0) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      activeIndex = Math.min(activeIndex + 1, currentItems.length - 1);
      render(currentItems);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      activeIndex = Math.max(activeIndex - 1, 0);
      render(currentItems);
    } else if (event.key === "Enter" && activeIndex >= 0) {
      event.preventDefault();
      choose(currentItems[activeIndex]);
    } else if (event.key === "Escape") {
      close();
    }
  });

  inputEl.addEventListener("blur", () => setTimeout(close, 100));

  return {
    /** The 3-letter code to actually search with: the chosen suggestion's
     *  code, or whatever the user typed if it already looks like one. */
    getCode() {
      if (inputEl.dataset.code) return inputEl.dataset.code;
      const typed = inputEl.value.trim().toUpperCase();
      return /^[A-Z]{3}$/.test(typed) ? typed : typed;
    },
    setCode(code, label) {
      inputEl.value = label || code;
      inputEl.dataset.code = code;
    },
  };
}

function renderProviderStrip(providers) {
  const el = document.getElementById("provider-strip");
  if (!el) return;
  el.textContent = "";
  for (const provider of providers || []) {
    const pill = document.createElement("span");
    pill.className = "provider-pill";
    pill.textContent = siteLabel(provider.site);
    pill.title = provider.description || "";
    el.appendChild(pill);
  }
}

async function loadProviderStrip() {
  try {
    const response = await fetch("/api/providers");
    if (!response.ok) return;
    const data = await response.json();
    renderProviderStrip(
      (data.enabled || []).map((site) => ({ site, description: data.descriptions[site] }))
    );
  } catch (err) {
    // non-essential UI chrome
  }
}

loadProviderStrip();
