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

function formatMoney(price, currency) {
  return `$${formatPrice(price)} ${currency || "USD"}`;
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
