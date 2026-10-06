// Watches page: create/list/remove watches, trigger an immediate check, and
// show a price-history sparkline per watch.

(function () {
  const form = document.getElementById("watch-form");
  if (!form) return;

  const statusEl = document.getElementById("watch-status");
  const listEl = document.getElementById("watches-list");
  const emptyEl = document.getElementById("watches-empty");

  wireAirportAutocomplete(
    document.getElementById("w-origin"),
    document.getElementById("w-origin-suggestions")
  );
  wireAirportAutocomplete(
    document.getElementById("w-destination"),
    document.getElementById("w-destination-suggestions")
  );

  const STATUS_TEXT = {
    ok: "Checked - found fares",
    no_results: "Checked - no fares found",
    all_providers_failing: "Checked - every provider failed",
    no_providers: "No providers enabled",
    error: "Check failed",
  };

  function formatRelativeTime(isoString) {
    if (!isoString) return "never";
    const then = new Date(isoString);
    const diffMinutes = Math.round((Date.now() - then.getTime()) / 60000);
    if (diffMinutes < 1) return "just now";
    if (diffMinutes < 60) return `${diffMinutes}m ago`;
    const diffHours = Math.round(diffMinutes / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    return `${Math.round(diffHours / 24)}d ago`;
  }

  // A tiny inline SVG line chart - no charting library needed for a few
  // dozen points, and it stays legible in both light and dark themes via
  // `currentColor`.
  function buildSparkline(points) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    const width = 320;
    const height = 64;
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("class", "sparkline");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "Price history chart");

    if (points.length < 2) {
      const text = document.createElementNS(svg.namespaceURI, "text");
      text.setAttribute("x", "10");
      text.setAttribute("y", String(height / 2));
      text.setAttribute("class", "sparkline-empty-text");
      text.textContent = "Not enough history yet";
      svg.appendChild(text);
      return svg;
    }

    const prices = points.map((p) => p.price);
    const min = Math.min(...prices);
    const max = Math.max(...prices);
    const span = max - min || 1;
    const padding = 6;

    const coords = points.map((point, index) => {
      const x = padding + (index / (points.length - 1)) * (width - padding * 2);
      const y = height - padding - ((point.price - min) / span) * (height - padding * 2);
      return [x, y];
    });

    const path = document.createElementNS(svg.namespaceURI, "path");
    path.setAttribute("d", coords.map((c, i) => `${i === 0 ? "M" : "L"}${c[0]},${c[1]}`).join(" "));
    path.setAttribute("class", "sparkline-line");
    svg.appendChild(path);

    const last = coords[coords.length - 1];
    const dot = document.createElementNS(svg.namespaceURI, "circle");
    dot.setAttribute("cx", String(last[0]));
    dot.setAttribute("cy", String(last[1]));
    dot.setAttribute("r", "3");
    dot.setAttribute("class", "sparkline-dot");
    svg.appendChild(dot);

    const title = document.createElementNS(svg.namespaceURI, "title");
    title.textContent = `Low $${formatPrice(min)} · High $${formatPrice(max)}`;
    svg.appendChild(title);

    return svg;
  }

  async function loadHistory(watchId, container) {
    container.textContent = "Loading history…";
    try {
      const response = await fetch(`/api/watches/${watchId}/history`);
      if (!response.ok) {
        container.textContent = "Could not load history.";
        return;
      }
      const data = await response.json();
      container.textContent = "";
      if (data.points.length === 0) {
        container.textContent = "No price history yet - run a check first.";
        return;
      }
      container.appendChild(buildSparkline(data.points));
      const summary = document.createElement("div");
      summary.className = "history-summary";
      const low = data.historical_min ? `All-time low: $${formatPrice(data.historical_min)}` : "";
      const alerts = `${data.alerts_sent} alert${data.alerts_sent === 1 ? "" : "s"} sent`;
      summary.textContent = [low, alerts].filter(Boolean).join(" · ");
      container.appendChild(summary);
    } catch (err) {
      container.textContent = "Could not load history.";
    }
  }

  function renderWatchCard(watch) {
    const card = document.createElement("article");
    card.className = "watch-card";

    const header = document.createElement("div");
    header.className = "watch-card-header";

    const routeEl = document.createElement("div");
    routeEl.className = "watch-route";
    routeEl.textContent = `${watch.origin} → ${watch.destination}`;
    header.appendChild(routeEl);

    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.className = "danger";
    removeButton.textContent = "Remove";
    removeButton.addEventListener("click", async () => {
      removeButton.disabled = true;
      await fetch(`/api/watches/${watch.id}`, { method: "DELETE" });
      loadWatches();
    });
    header.appendChild(removeButton);
    card.appendChild(header);

    const meta = document.createElement("div");
    meta.className = "watch-meta";
    const dates = watch.return_date
      ? `${watch.depart_date} → ${watch.return_date}`
      : `${watch.depart_date} (one way)`;
    const cabinLabel = watch.cabin.replace("_", " ");
    const stopsLabel =
      watch.max_stops === null || watch.max_stops === undefined
        ? ""
        : ` · max ${watch.max_stops} stop${watch.max_stops === 1 ? "" : "s"}`;
    meta.textContent = `${dates} · ${watch.adults} passenger${watch.adults === 1 ? "" : "s"} · ${cabinLabel}${stopsLabel}`;
    card.appendChild(meta);

    const priceRow = document.createElement("div");
    priceRow.className = "watch-price-row";
    const targetEl = document.createElement("span");
    targetEl.className = "watch-target";
    targetEl.textContent = watch.target_price
      ? `Target: $${formatPrice(watch.target_price)}`
      : "Alerts on any new low";
    priceRow.appendChild(targetEl);
    if (watch.last_price) {
      const lastPriceEl = document.createElement("span");
      lastPriceEl.className = "watch-last-price";
      lastPriceEl.textContent = `Last seen: $${formatPrice(watch.last_price)}`;
      priceRow.appendChild(lastPriceEl);
    }
    card.appendChild(priceRow);

    const statusRow = document.createElement("div");
    statusRow.className = "watch-status-row";
    const statusBadge = document.createElement("span");
    statusBadge.className = "watch-status-badge " + (watch.last_status || "pending");
    statusBadge.textContent = watch.last_status
      ? STATUS_TEXT[watch.last_status] || watch.last_status
      : "Not checked yet";
    statusRow.appendChild(statusBadge);
    const checkedEl = document.createElement("span");
    checkedEl.className = "watch-checked-at";
    checkedEl.textContent = watch.last_checked_at
      ? `· ${formatRelativeTime(watch.last_checked_at)}`
      : "";
    statusRow.appendChild(checkedEl);
    card.appendChild(statusRow);

    const actions = document.createElement("div");
    actions.className = "watch-actions";

    const checkButton = document.createElement("button");
    checkButton.type = "button";
    checkButton.className = "secondary";
    checkButton.textContent = "Check now";
    checkButton.addEventListener("click", async () => {
      checkButton.disabled = true;
      const original = checkButton.textContent;
      checkButton.textContent = "Checking…";
      try {
        const response = await fetch(`/api/watches/${watch.id}/check`, { method: "POST" });
        if (response.ok) {
          loadWatches();
        } else {
          const body = await response.json().catch(() => ({}));
          checkButton.textContent = body.detail || "Check failed";
          setTimeout(() => {
            checkButton.textContent = original;
            checkButton.disabled = false;
          }, 2500);
        }
      } catch (err) {
        checkButton.textContent = "Check failed";
        setTimeout(() => {
          checkButton.textContent = original;
          checkButton.disabled = false;
        }, 2500);
      }
    });
    actions.appendChild(checkButton);

    const historyButton = document.createElement("button");
    historyButton.type = "button";
    historyButton.className = "link-button";
    historyButton.textContent = "Show price history";
    const historyContainer = document.createElement("div");
    historyContainer.className = "watch-history";
    historyContainer.hidden = true;
    historyButton.addEventListener("click", () => {
      const willShow = historyContainer.hidden;
      historyContainer.hidden = !willShow;
      historyButton.textContent = willShow ? "Hide price history" : "Show price history";
      if (willShow && !historyContainer.dataset.loaded) {
        historyContainer.dataset.loaded = "1";
        loadHistory(watch.id, historyContainer);
      }
    });
    actions.appendChild(historyButton);
    card.appendChild(actions);
    card.appendChild(historyContainer);

    return card;
  }

  async function loadWatches() {
    const response = await fetch("/api/watches");
    const watches = await response.json();
    listEl.textContent = "";
    emptyEl.hidden = watches.length !== 0;
    for (const watch of watches) {
      listEl.appendChild(renderWatchCard(watch));
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const targetPriceValue = document.getElementById("w-target_price").value;
    const alertEmailValue = document.getElementById("w-alert_email").value.trim();

    const payload = {
      origin: document.getElementById("w-origin").value.trim().toUpperCase(),
      destination: document.getElementById("w-destination").value.trim().toUpperCase(),
      depart_date: document.getElementById("w-depart_date").value,
      return_date: document.getElementById("w-return_date").value || null,
      adults: parseInt(document.getElementById("w-adults").value, 10) || 1,
      cabin: document.getElementById("w-cabin").value,
      target_price: targetPriceValue ? targetPriceValue : null,
      alert_email: alertEmailValue || null,
    };

    const response = await fetch("/api/watches", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (response.ok) {
      showStatus(statusEl, "Watch added.", "info");
      form.reset();
      loadWatches();
    } else {
      const body = await response.json().catch(() => ({}));
      const detail = Array.isArray(body.detail) ? body.detail.map((d) => d.msg).join("; ") : body.detail;
      showStatus(statusEl, `Could not add watch: ${detail || response.statusText}`, "error");
    }
  });

  loadWatches();
})();
