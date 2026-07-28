// Vanilla JS for both the search page and the watches page - no build step,
// no framework, matches this being a small local single-user tool.

function showStatus(el, message, kind) {
  el.textContent = message;
  el.className = "status " + kind;
  el.hidden = false;
}

function safeHref(url) {
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

function renderSiteStatuses(container, siteStatuses) {
  container.textContent = "";
  for (const [site, status] of Object.entries(siteStatuses || {})) {
    const pill = document.createElement("span");
    pill.className = "site-status-pill " + status;
    pill.textContent = `${site}: ${status.replace(/_/g, " ")}`;
    container.appendChild(pill);
  }
}

function setupSearchPage() {
  const form = document.getElementById("search-form");
  if (!form) return;

  const statusEl = document.getElementById("search-status");
  const siteStatusesEl = document.getElementById("site-statuses");
  const table = document.getElementById("results-table");
  const tbody = document.getElementById("results-body");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const origin = document.getElementById("origin").value.trim().toUpperCase();
    const destination = document.getElementById("destination").value.trim().toUpperCase();
    const departDate = document.getElementById("depart_date").value;
    const returnDate = document.getElementById("return_date").value || null;

    showStatus(statusEl, "Searching Google Flights - this can take 10-20 seconds...", "info");
    table.hidden = true;
    tbody.textContent = "";
    siteStatusesEl.textContent = "";

    try {
      const response = await fetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          origin,
          destination,
          depart_date: departDate,
          return_date: returnDate,
        }),
      });

      if (!response.ok) {
        const errorBody = await response.json().catch(() => ({}));
        showStatus(statusEl, `Search failed: ${errorBody.detail || response.statusText}`, "error");
        return;
      }

      const data = await response.json();
      renderSiteStatuses(siteStatusesEl, data.site_statuses);

      if (data.fares.length === 0) {
        showStatus(statusEl, "No fares found for that route/date.", "info");
        return;
      }

      statusEl.hidden = true;
      table.hidden = false;
      for (const fare of data.fares) {
        const row = document.createElement("tr");

        const priceCell = document.createElement("td");
        priceCell.textContent = `$${fare.price} ${fare.currency}`;
        row.appendChild(priceCell);

        const airlineCell = document.createElement("td");
        airlineCell.textContent = fare.airline || "-";
        row.appendChild(airlineCell);

        const siteCell = document.createElement("td");
        siteCell.textContent = fare.site;
        row.appendChild(siteCell);

        const linkCell = document.createElement("td");
        const href = safeHref(fare.deep_link);
        if (href) {
          const link = document.createElement("a");
          link.href = href;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          link.textContent = "View / book";
          linkCell.appendChild(link);
        }
        row.appendChild(linkCell);

        const watchCell = document.createElement("td");
        const watchButton = document.createElement("button");
        watchButton.className = "secondary";
        watchButton.type = "button";
        watchButton.textContent = "Watch this route";
        watchButton.addEventListener("click", async () => {
          watchButton.disabled = true;
          try {
            const watchResponse = await fetch("/api/watches", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                origin,
                destination,
                depart_date: departDate,
                return_date: returnDate,
              }),
            });
            if (watchResponse.ok) {
              watchButton.textContent = "Watching";
            } else {
              const body = await watchResponse.json().catch(() => ({}));
              watchButton.textContent = body.detail === undefined ? "Failed" : "Already watched";
            }
          } catch (err) {
            watchButton.textContent = "Failed";
          }
        });
        watchCell.appendChild(watchButton);
        row.appendChild(watchCell);

        tbody.appendChild(row);
      }
    } catch (err) {
      showStatus(statusEl, `Search failed: ${err}`, "error");
    }
  });
}

async function loadWatches() {
  const tbody = document.getElementById("watches-body");
  if (!tbody) return;

  const response = await fetch("/api/watches");
  const watches = await response.json();
  tbody.textContent = "";

  for (const watch of watches) {
    const row = document.createElement("tr");

    const routeCell = document.createElement("td");
    routeCell.textContent = `${watch.origin} -> ${watch.destination}`;
    row.appendChild(routeCell);

    const datesCell = document.createElement("td");
    datesCell.textContent = watch.return_date
      ? `${watch.depart_date} - ${watch.return_date}`
      : `${watch.depart_date} (one way)`;
    row.appendChild(datesCell);

    const targetCell = document.createElement("td");
    targetCell.textContent = watch.target_price ? `$${watch.target_price}` : "-";
    row.appendChild(targetCell);

    const statusCell = document.createElement("td");
    statusCell.textContent = watch.is_active ? "Active" : "Removed";
    row.appendChild(statusCell);

    const actionCell = document.createElement("td");
    if (watch.is_active) {
      const removeButton = document.createElement("button");
      removeButton.className = "danger";
      removeButton.type = "button";
      removeButton.textContent = "Remove";
      removeButton.addEventListener("click", async () => {
        removeButton.disabled = true;
        await fetch(`/api/watches/${watch.id}`, { method: "DELETE" });
        loadWatches();
      });
      actionCell.appendChild(removeButton);
    }
    row.appendChild(actionCell);

    tbody.appendChild(row);
  }
}

function setupWatchesPage() {
  const form = document.getElementById("watch-form");
  if (!form) return;

  const statusEl = document.getElementById("watch-status");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const targetPriceValue = document.getElementById("w-target_price").value;
    const alertEmailValue = document.getElementById("w-alert_email").value.trim();

    const payload = {
      origin: document.getElementById("w-origin").value.trim().toUpperCase(),
      destination: document.getElementById("w-destination").value.trim().toUpperCase(),
      depart_date: document.getElementById("w-depart_date").value,
      return_date: document.getElementById("w-return_date").value || null,
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
      showStatus(statusEl, `Could not add watch: ${body.detail || response.statusText}`, "error");
    }
  });

  loadWatches();
}

setupSearchPage();
setupWatchesPage();
