// Search page: build a SearchQuery from the form, render results as cards,
// resolve booking links on demand, and let the user save a watch straight
// from a result.

(function () {
  const form = document.getElementById("search-form");
  if (!form) return;

  const statusEl = document.getElementById("search-status");
  const siteStatusesEl = document.getElementById("site-statuses");
  const toolbarEl = document.getElementById("results-toolbar");
  const countEl = document.getElementById("results-count");
  const listEl = document.getElementById("results-list");
  const emptyEl = document.getElementById("results-empty");
  const sortSelect = document.getElementById("sort-by");
  const refreshButton = document.getElementById("search-refresh");
  const submitButton = document.getElementById("search-submit");

  const originInput = document.getElementById("origin");
  const destinationInput = document.getElementById("destination");
  const originAuto = wireAirportAutocomplete(originInput, document.getElementById("origin-suggestions"));
  const destinationAuto = wireAirportAutocomplete(destinationInput, document.getElementById("destination-suggestions"));

  let lastFares = [];
  let lastQuery = null;

  document.getElementById("swap-airports").addEventListener("click", () => {
    const originValue = originInput.value;
    const originCode = originInput.dataset.code;
    originInput.value = destinationInput.value;
    if (destinationInput.dataset.code) originInput.dataset.code = destinationInput.dataset.code;
    else delete originInput.dataset.code;
    destinationInput.value = originValue;
    if (originCode) destinationInput.dataset.code = originCode;
    else delete destinationInput.dataset.code;
  });

  const returnDateInput = document.getElementById("return_date");
  const clearReturnButton = document.getElementById("clear-return");
  clearReturnButton.addEventListener("click", () => {
    returnDateInput.value = "";
  });

  function currentQuery(refresh) {
    const maxStopsValue = document.getElementById("max_stops").value;
    return {
      origin: originAuto.getCode(),
      destination: destinationAuto.getCode(),
      depart_date: document.getElementById("depart_date").value,
      return_date: returnDateInput.value || null,
      adults: parseInt(document.getElementById("adults").value, 10) || 1,
      cabin: document.getElementById("cabin").value,
      max_stops: maxStopsValue === "" ? null : parseInt(maxStopsValue, 10),
      refresh: !!refresh,
    };
  }

  const STATUS_LABELS = {
    ok: "ok",
    no_results: "no results",
    blocked_or_structure_changed: "blocked or changed",
    not_configured: "not set up",
    error: "error",
  };

  function renderSiteStatuses(statuses, diagnostics) {
    siteStatusesEl.textContent = "";
    for (const [site, status] of Object.entries(statuses || {})) {
      const pill = document.createElement("span");
      pill.className = "site-status-pill " + status;
      pill.textContent = `${siteLabel(site)}: ${STATUS_LABELS[status] || status}`;
      const detail = (diagnostics || {})[site];
      if (detail) pill.title = detail;
      siteStatusesEl.appendChild(pill);
    }
  }

  function sortFares(fares, sortBy) {
    const copy = fares.slice();
    if (sortBy === "duration") {
      copy.sort((a, b) => (a.duration_minutes ?? Infinity) - (b.duration_minutes ?? Infinity));
    } else if (sortBy === "depart") {
      copy.sort((a, b) => (a.depart_at || "").localeCompare(b.depart_at || ""));
    } else {
      copy.sort((a, b) => parseFloat(a.price) - parseFloat(b.price));
    }
    return copy;
  }

  function buildLayoverText(fare) {
    if (!fare.layovers || fare.layovers.length === 0) return "";
    return fare.layovers
      .map((l) => `${formatDuration(l.duration_minutes)} in ${l.city || l.airport}`)
      .join(", ");
  }

  async function handleBookClick(button, fare) {
    const directHref = safeHref(fare.booking_url);
    if (directHref) {
      window.open(directHref, "_blank", "noopener,noreferrer");
      return;
    }
    button.disabled = true;
    button.textContent = "Finding this flight…";
    try {
      const response = await fetch("/api/booking-link", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...lastQuery, fare }),
      });
      if (response.ok) {
        const body = await response.json();
        fare.booking_url = body.booking_url;
        const href = safeHref(body.booking_url);
        button.textContent = "Book this flight";
        button.disabled = false;
        if (href) window.open(href, "_blank", "noopener,noreferrer");
        return;
      }
    } catch (err) {
      // fall through to the search-page fallback below
    }
    button.disabled = false;
    button.textContent = "View search results";
    const fallback = safeHref(fare.deep_link);
    if (fallback) window.open(fallback, "_blank", "noopener,noreferrer");
  }

  async function handleWatchClick(button, fare) {
    button.disabled = true;
    const original = button.textContent;
    try {
      const response = await fetch("/api/watches", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          origin: lastQuery.origin,
          destination: lastQuery.destination,
          depart_date: lastQuery.depart_date,
          return_date: lastQuery.return_date,
          adults: lastQuery.adults,
          cabin: lastQuery.cabin,
          max_stops: lastQuery.max_stops,
          target_price: fare.price,
        }),
      });
      if (response.ok) {
        button.textContent = "Watching ✓";
      } else {
        const body = await response.json().catch(() => ({}));
        button.textContent =
          response.status === 409 ? "Already watching this route" : body.detail || "Could not watch";
        button.disabled = false;
      }
    } catch (err) {
      button.textContent = original;
      button.disabled = false;
    }
  }

  function renderFareCard(fare) {
    const card = document.createElement("article");
    card.className = "fare-card";

    const priceCol = document.createElement("div");
    priceCol.className = "fare-price-col";
    const price = document.createElement("div");
    price.className = "fare-price";
    price.textContent = formatMoney(fare.price, fare.currency);
    priceCol.appendChild(price);
    const siteBadge = document.createElement("span");
    siteBadge.className = "fare-site-badge " + (fare.site === "demo" ? "demo" : "");
    siteBadge.textContent = siteLabel(fare.site);
    priceCol.appendChild(siteBadge);
    card.appendChild(priceCol);

    const detailCol = document.createElement("div");
    detailCol.className = "fare-detail-col";

    const airlineRow = document.createElement("div");
    airlineRow.className = "fare-airline-row";
    airlineRow.textContent = fare.airline || "Unknown airline";
    if (fare.operated_by) {
      const op = document.createElement("span");
      op.className = "fare-operated-by";
      op.textContent = ` operated by ${fare.operated_by}`;
      airlineRow.appendChild(op);
    }
    detailCol.appendChild(airlineRow);

    const timeRow = document.createElement("div");
    timeRow.className = "fare-time-row";
    if (fare.depart_time && fare.arrive_time) {
      timeRow.textContent = `${fare.depart_time} → ${fare.arrive_time}`;
    }
    const durationSpan = document.createElement("span");
    durationSpan.className = "fare-duration";
    durationSpan.textContent = ` · ${formatDuration(fare.duration_minutes)}`;
    timeRow.appendChild(durationSpan);
    const stopsSpan = document.createElement("span");
    stopsSpan.className = "fare-stops " + (fare.stops === 0 ? "nonstop" : "has-stops");
    stopsSpan.textContent = ` · ${formatStops(fare.stops)}`;
    timeRow.appendChild(stopsSpan);
    detailCol.appendChild(timeRow);

    const layoverText = buildLayoverText(fare);
    if (layoverText) {
      const layoverRow = document.createElement("div");
      layoverRow.className = "fare-layover-row";
      layoverRow.textContent = layoverText;
      detailCol.appendChild(layoverRow);
    }

    const bagsRow = document.createElement("div");
    bagsRow.className = "fare-bags-row";
    const bagParts = [];
    if (fare.carry_on_bags_included !== null && fare.carry_on_bags_included !== undefined) {
      bagParts.push(`${fare.carry_on_bags_included} carry-on`);
    }
    if (fare.checked_bags_included !== null && fare.checked_bags_included !== undefined) {
      bagParts.push(`${fare.checked_bags_included} checked`);
    }
    if (bagParts.length) bagsRow.textContent = bagParts.join(", ") + " included";
    if (bagsRow.textContent) detailCol.appendChild(bagsRow);

    card.appendChild(detailCol);

    const actionCol = document.createElement("div");
    actionCol.className = "fare-action-col";

    const bookButton = document.createElement("button");
    bookButton.type = "button";
    bookButton.className = "primary";
    bookButton.textContent = fare.booking_url ? "Book this flight" : "Get direct link";
    bookButton.addEventListener("click", () => handleBookClick(bookButton, fare));
    actionCol.appendChild(bookButton);

    const searchLink = safeHref(fare.deep_link);
    if (searchLink) {
      const viewLink = document.createElement("a");
      viewLink.href = searchLink;
      viewLink.target = "_blank";
      viewLink.rel = "noopener noreferrer";
      viewLink.className = "secondary-link";
      viewLink.textContent = "View all options";
      actionCol.appendChild(viewLink);
    }

    const watchButton = document.createElement("button");
    watchButton.type = "button";
    watchButton.className = "watch-button";
    watchButton.textContent = `Watch - alert at $${fare.price}`;
    watchButton.addEventListener("click", () => handleWatchClick(watchButton, fare));
    actionCol.appendChild(watchButton);

    card.appendChild(actionCol);
    return card;
  }

  function renderResults(fares) {
    const sorted = sortFares(fares, sortSelect.value);
    listEl.textContent = "";
    for (const fare of sorted) {
      listEl.appendChild(renderFareCard(fare));
    }
  }

  sortSelect.addEventListener("change", () => {
    if (lastFares.length) renderResults(lastFares);
  });

  async function runSearch(refresh) {
    const query = currentQuery(refresh);
    if (!query.origin || !query.destination) {
      showStatus(statusEl, "Enter both an origin and a destination.", "error");
      return;
    }

    lastQuery = query;
    submitButton.disabled = true;
    refreshButton.disabled = true;
    showStatus(statusEl, "Searching for flights - this can take 10-20 seconds…", "info");
    toolbarEl.hidden = true;
    emptyEl.hidden = true;
    listEl.textContent = "";
    siteStatusesEl.textContent = "";

    try {
      const response = await fetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(query),
      });

      if (!response.ok) {
        const errorBody = await response.json().catch(() => ({}));
        const detail = Array.isArray(errorBody.detail)
          ? errorBody.detail.map((d) => d.msg).join("; ")
          : errorBody.detail;
        showStatus(statusEl, `Search failed: ${detail || response.statusText}`, "error");
        return;
      }

      const data = await response.json();
      renderSiteStatuses(data.site_statuses, data.site_diagnostics);
      lastFares = data.fares;

      if (data.fares.length === 0) {
        hideStatus(statusEl);
        emptyEl.hidden = false;
        return;
      }

      hideStatus(statusEl);
      toolbarEl.hidden = false;
      countEl.textContent =
        `${data.fares.length} fare${data.fares.length === 1 ? "" : "s"} found` +
        (data.from_cache ? " (cached)" : "");
      refreshButton.hidden = false;
      renderResults(data.fares);
    } catch (err) {
      showStatus(statusEl, `Search failed: ${err}`, "error");
    } finally {
      submitButton.disabled = false;
      refreshButton.disabled = false;
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    runSearch(false);
  });

  refreshButton.addEventListener("click", () => runSearch(true));
})();
