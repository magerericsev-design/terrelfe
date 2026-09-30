const data = window.SOLAR_DASHBOARD_DATA;
const weatherData = window.SOLAR_WEATHER_DATA || null;
const cachedLinkyData = window.LINKY_DATA || null;

if (!data) {
  document.body.innerHTML =
    '<main class="main"><article class="panel"><h1>Donnees introuvables</h1><p>Relancez regenerer-site.cmd pour creer data.js.</p></article></main>';
  throw new Error("SOLAR_DASHBOARD_DATA missing");
}

const safeStorage = {
  get(key) {
    try { return window.localStorage.getItem(key); } catch (_) { return null; }
  },
  set(key, value) {
    try { window.localStorage.setItem(key, value); } catch (_) { /* mode fichier local / aperçu sandbox */ }
  },
};

const state = {
  selectedYear: data.meta.latest_year,
  highlightedYear: data.meta.latest_year,
  metric: "energy",
  theme: safeStorage.get("solar-theme") || "light",
  dailyMode: "year",
  linky: cachedLinkyData,
  linkyDaily: [],
  linkyReconciliation: null,
};

const CONSUMPTION_MATRIX_LAST_YEAR = 2030;
const DEFAULT_MONTH_LABELS = [
  "Janvier",
  "Février",
  "Mars",
  "Avril",
  "Mai",
  "Juin",
  "Juillet",
  "Août",
  "Septembre",
  "Octobre",
  "Novembre",
  "Décembre",
];

const colors = () => {
  const style = getComputedStyle(document.documentElement);
  return {
    text: style.getPropertyValue("--text").trim(),
    muted: style.getPropertyValue("--muted").trim(),
    border: style.getPropertyValue("--border").trim(),
    line: style.getPropertyValue("--line").trim(),
    accent: style.getPropertyValue("--accent").trim(),
    accent2: style.getPropertyValue("--accent-2").trim(),
    accent3: style.getPropertyValue("--accent-3").trim(),
    solar: style.getPropertyValue("--solar").trim(),
    good: style.getPropertyValue("--good").trim(),
    warn: style.getPropertyValue("--warn").trim(),
    climateHeat: style.getPropertyValue("--climate-heat").trim(),
    climateCold: style.getPropertyValue("--climate-cold").trim(),
    climateRain: style.getPropertyValue("--climate-rain").trim(),
    climateStorm: style.getPropertyValue("--climate-storm").trim(),
    climateDry: style.getPropertyValue("--climate-dry").trim(),
    surface2: style.getPropertyValue("--surface-2").trim(),
    years: {
      2023: style.getPropertyValue("--year-2023").trim(),
      2024: style.getPropertyValue("--year-2024").trim(),
      2025: style.getPropertyValue("--year-2025").trim(),
      2026: style.getPropertyValue("--year-2026").trim(),
      2027: style.getPropertyValue("--year-2027").trim(),
      2028: style.getPropertyValue("--year-2028").trim(),
      2029: style.getPropertyValue("--year-2029").trim(),
      2030: style.getPropertyValue("--year-2030").trim(),
    },
  };
};

const el = (id) => document.getElementById(id);

const formatNumber = (value, digits = 0) =>
  new Intl.NumberFormat("fr-FR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(Number(value || 0));

const formatCurrency = (value, digits = 0) =>
  new Intl.NumberFormat("fr-FR", {
    style: "currency",
    currency: "EUR",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(Number(value || 0));

const formatKwh = (value, digits = 0) => `${formatNumber(value, digits)} kWh`;
const formatKwc = (value) => `${formatNumber(value, 2)} kWc`;
const formatPercent = (value, digits = 1) => `${formatNumber(value, digits)} %`;
const formatTemp = (value, digits = 1) => (value == null ? "--" : `${formatNumber(value, digits)} °C`);
const formatMm = (value, digits = 0) => (value == null ? "--" : `${formatNumber(value, digits)} mm`);
const formatDays = (value, digits = 0) => `${formatNumber(value, digits)} j`;
const formatKmh = (value, digits = 0) => (value == null ? "--" : `${formatNumber(value, digits)} km/h`);

const formatChartValue = (value, unit) => {
  if (unit === "eur") return formatCurrency(value);
  if (unit === "days") return formatDays(value);
  if (unit === "mm") return formatMm(value);
  if (unit === "temp") return formatTemp(value);
  return formatKwh(value, unit === "kwh-precise" ? 1 : 0);
};

const formatDate = (isoDate) => {
  if (!isoDate) return "--";
  return new Intl.DateTimeFormat("fr-FR", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(new Date(`${isoDate}T00:00:00`));
};

const formatDateTime = (isoDate) => {
  if (!isoDate) return "--";
  return new Intl.DateTimeFormat("fr-FR", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(isoDate));
};

const yearByValue = (year) => data.years.find((item) => item.year === Number(year));
const weatherYearByValue = (year) =>
  weatherData && Array.isArray(weatherData.years)
    ? weatherData.years.find((item) => item.year === Number(year))
    : null;
const latestWeatherYear = () =>
  weatherData && Array.isArray(weatherData.years) && weatherData.years.length
    ? weatherData.years[weatherData.years.length - 1]
    : null;
const monthsForYear = (year) => data.months[String(year)] || [];
const dailyForYear = (year) => data.daily.filter((item) => item.year === Number(year));
const formatStatusLabel = (status) =>
  ({
    "Annee complete": "Année complète",
    "En cours": "En cours",
    "Mise en service": "Mise en service",
    Transition: "Transition",
    Historique: "Historique",
  })[status] || status;
const referenceYear = () =>
  data.years.find((item) => item.is_first_full_year) ||
  data.years.find((item) => item.coverage_percent >= 99) ||
  data.years[data.years.length - 1];
const hasMatrixRows = () => Array.isArray(data.consumption_matrix) && data.consumption_matrix.length > 0;
const monthLabels = () => {
  if (hasMatrixRows()) {
    const row = data.consumption_matrix.find((item) => Array.isArray(item.months) && item.months.length);
    if (row) {
      return DEFAULT_MONTH_LABELS.map((fallback, index) => row.months[index]?.label || fallback);
    }
  }

  return DEFAULT_MONTH_LABELS.map((fallback, index) => {
    const sample = data.years
      .map((year) => monthsForYear(year.year)[index])
      .find((month) => month && month.label);
    return sample ? sample.label : fallback;
  });
};

const formatLinkyDate = (value, includeTime = false) => {
  if (!value) return "--";
  const parsed = new Date(value.length === 10 ? `${value}T12:00:00` : value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("fr-FR", includeTime
    ? { dateStyle: "short", timeStyle: "short" }
    : { dateStyle: "short" }).format(parsed);
};

function linkyStatusLabel(status) {
  return {
    up_to_date: "À jour",
    demo: "Mode TEST",
    never_synced: "À synchroniser",
    not_configured: "À configurer",
    attention: "À vérifier",
    authorization_required: "Autorisation requise",
    temporarily_unavailable: "Hors ligne",
    rate_limited: "Limite temporaire",
  }[status] || "Indisponible";
}

function renderLinkyStatus(payload, serviceAvailable = true) {
  state.linky = payload || null;
  const status = payload?.status || (serviceAvailable ? "never_synced" : "temporarily_unavailable");
  const badge = el("linkyStatus");
  badge.dataset.status = status;
  badge.querySelector("span").textContent = linkyStatusLabel(status);
  el("linkyLastData").textContent = formatLinkyDate(payload?.last_daily_data || payload?.last_data);
  el("linkyLastSync").textContent = formatLinkyDate(payload?.last_sync, true);
  const curves = payload?.load_curves || {};
  const curveCandidates = Object.entries(curves)
    .filter(([, value]) => value?.last_measurement)
    .sort((left, right) => String(right[1].last_measurement).localeCompare(String(left[1].last_measurement)));
  const latestCurve = curveCandidates[0]?.[1] || null;
  el("linkyLastCurveMeasurement").textContent = formatLinkyDate(latestCurve?.last_measurement, true);
  el("linkyLastCompleteDay").textContent = formatLinkyDate(latestCurve?.last_complete_day);
  const summary = payload?.summary;
  el("linkyStats").hidden = !summary;
  if (summary) {
    el("linkyConsumption").textContent = `${formatNumber(summary.consumption_kwh, 1)} kWh`;
    el("linkyInjection").textContent = `${formatNumber(summary.injection_kwh, 1)} kWh`;
  }
  const isMock = payload?.mode === "mock";
  el("linkySection").classList.toggle("is-demo", isMock);
  el("linkyModeNote").textContent = isMock
    ? "TEST — données fictives isolées. Elles ne remplacent jamais vos relevés réels."
    : summary
      ? `Consommation depuis le ${formatLinkyDate(summary.consumption_start || summary.start)} · injection depuis le ${formatLinkyDate(summary.injection_start || summary.start)}. ${summary.note || ""}`
      : "Les données solaires Excel restent la référence du cockpit.";
  el("linkySyncButton").disabled = !serviceAvailable;
  el("linkyHistoryButton").disabled = !serviceAvailable;
  renderLinkyDetails();
}

function renderLinkyDetails() {
  const rows = Array.isArray(state.linkyDaily) ? state.linkyDaily : [];
  const table = el("linkyDailyTable");
  if (!table) return;
  el("linkyRowsStatus").textContent = rows.length ? `${formatNumber(rows.length)} jours` : "Résumé disponible";
  const recent = rows.slice(-31);
  const totalConsumption = recent.reduce((sum, row) => sum + Number(row.consumption_wh || 0) / 1000, 0);
  const totalInjection = recent.reduce((sum, row) => sum + Number(row.production_wh || row.injection_wh || 0) / 1000, 0);
  el("linkyDetailSummary").innerHTML = rows.length
    ? `<div><span>Période affichée</span><strong>${formatLinkyDate(recent[0]?.day)} → ${formatLinkyDate(recent.at(-1)?.day)}</strong></div><div><span>Consommation</span><strong>${formatKwh(totalConsumption, 1)}</strong></div><div><span>Injection</span><strong>${formatKwh(totalInjection, 1)}</strong></div>`
    : `<p>Le résumé cumulé reste visible. Lancez le cockpit local pour charger le détail quotidien depuis la base Linky.</p>`;
  table.innerHTML = recent.length
    ? recent.slice().reverse().map((row) => `<tr><td>${formatLinkyDate(row.day)}</td><td>${row.consumption_wh == null ? "--" : formatKwh(Number(row.consumption_wh) / 1000, 2)}</td><td>${(row.production_wh ?? row.injection_wh) == null ? "--" : formatKwh(Number(row.production_wh ?? row.injection_wh) / 1000, 2)}</td><td>${row.max_power_va == null ? "--" : `${formatNumber(row.max_power_va)} VA`}</td></tr>`).join("")
    : `<tr><td colspan="4">Aucun détail quotidien dans la copie statique.</td></tr>`;
}

function reconcileLinkyWithExcel(rows) {
  if (!Array.isArray(rows) || !rows.length) return null;
  const excelByDate = new Map(data.daily.map((row) => [row.date, Number(row.consumption_kwh)]));
  const common = rows.filter((row) => row.day && row.consumption_wh != null && excelByDate.has(row.day));
  if (!common.length) return null;

  const excelKwh = common.reduce((total, row) => total + excelByDate.get(row.day), 0);
  const linkyKwh = common.reduce((total, row) => total + Number(row.consumption_wh) / 1000, 0);
  const deltaKwh = linkyKwh - excelKwh;
  return {
    days: common.length,
    start: common[0].day,
    end: common[common.length - 1].day,
    excelKwh,
    linkyKwh,
    deltaKwh,
    coherent: Math.abs(deltaKwh) <= Math.max(0.1, common.length * 0.01),
  };
}

async function linkyRequest(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.message || "Le service Linky n'a pas répondu correctement.");
  return payload;
}

async function refreshLinkyStatus() {
  try {
    const [payload, dailyPayload] = await Promise.all([
      linkyRequest("/api/linky/status"),
      linkyRequest("/api/linky/daily"),
    ]);
    state.linkyDaily = Array.isArray(dailyPayload.rows) ? dailyPayload.rows : [];
    state.linkyReconciliation = reconcileLinkyWithExcel(dailyPayload.rows);
    renderLinkyStatus(payload, true);
    if (el("qualityStrip")) renderQualityStrip();
    return payload;
  } catch (_) {
    state.linkyDaily = [];
    state.linkyReconciliation = null;
    renderLinkyStatus(cachedLinkyData, false);
    el("linkyMessage").textContent = location.protocol === "file:"
      ? "Ouvrez le cockpit avec demarrer-cockpit.cmd pour activer Linky."
      : "Service local indisponible; les dernières données enregistrées restent affichées.";
    return null;
  }
}

async function runLinkyAction(path, body) {
  const syncButton = el("linkySyncButton");
  const historyButton = el("linkyHistoryButton");
  syncButton.disabled = true;
  historyButton.disabled = true;
  el("linkyMessage").textContent = "Synchronisation en cours…";
  try {
    const result = await linkyRequest(path, { method: "POST", body: JSON.stringify(body || {}) });
    renderLinkyStatus(result.dashboard, true);
    const imported = result.streams.reduce((total, stream) => total + (stream.rows || 0), 0);
    el("linkyMessage").textContent = result.status === "ok"
      ? `Mise à jour terminée : ${formatNumber(imported)} mesures reçues.`
      : "Mise à jour partielle : les anciennes données ont été conservées.";
  } catch (error) {
    el("linkyMessage").textContent = error.message;
    await refreshLinkyStatus();
  } finally {
    syncButton.disabled = false;
    historyButton.disabled = false;
  }
}

function setupLinky() {
  renderLinkyStatus(cachedLinkyData, true);
  el("linkySyncButton").addEventListener("click", () => runLinkyAction("/api/linky/sync"));
  el("linkyHistoryButton").addEventListener("click", () => {
    const start = el("linkyHistoryStart").value;
    if (!start) {
      el("linkyMessage").textContent = "Choisissez une date de début.";
      return;
    }
    runLinkyAction("/api/linky/import-history", { start });
  });
  refreshLinkyStatus();
}
const hasMonthData = (month) => {
  if (!month) return false;
  if (typeof month.days === "number") return month.days > 0;
  return month.consumption_kwh !== null && month.consumption_kwh !== undefined && month.consumption_kwh !== "";
};
const monthlyConsumptionRows = () => {
  if (hasMatrixRows()) {
    const labels = monthLabels();
    const sourceRows = new Map(data.consumption_matrix.map((row) => [Number(row.year), row]));
    const firstYear = Math.min(...data.consumption_matrix.map((row) => Number(row.year)));
    const lastYear = Math.max(CONSUMPTION_MATRIX_LAST_YEAR, ...data.consumption_matrix.map((row) => Number(row.year)));

    return Array.from({ length: lastYear - firstYear + 1 }, (_, index) => firstYear + index).map((year) => {
      const row = sourceRows.get(year) || {
        year,
        filled_months: 0,
        months: labels.map((label, monthIndex) => ({
          month: monthIndex + 1,
          label,
          consumption_kwh: null,
        })),
        total_kwh: null,
        average_month_kwh: null,
      };
      const yearData = yearByValue(row.year);
      return {
        year: row.year,
        status: yearData ? formatStatusLabel(yearData.status) : "À venir",
        isSelectable: Boolean(yearData),
        months: row.months || [],
        total_kwh: row.total_kwh,
        average_month_kwh: row.average_month_kwh,
      };
    });
  }

  return data.years.map((year) => {
    const months = monthsForYear(year.year);
    const filledMonths = months.filter(hasMonthData).length;
    return {
      year: year.year,
      status: formatStatusLabel(year.status),
      isSelectable: true,
      months,
      total_kwh: year.consumption_kwh,
      average_month_kwh: filledMonths ? year.consumption_kwh / filledMonths : null,
    };
  });
};

const formatSignedPercent = (value, digits = 1) => {
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatPercent(value, digits)}`;
};

const formatSignedValue = (value, suffix = "", digits = 0) => {
  if (value == null) return "--";
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatNumber(value, digits)}${suffix}`;
};

const formatDateRange = (start, end) => {
  if (!start) return "--";
  if (!end || end === start) return formatDate(start);
  return `${formatDate(start)} - ${formatDate(end)}`;
};

const climateDeltaText = (year, delta, suffix, digits = 0) => {
  if (!year || year.coverage_percent < 95) {
    return `${formatPercent(year?.coverage_percent || 0)} de l'année chargée`;
  }
  return `${formatSignedValue(delta, suffix, digits)} vs normale ${weatherData?.normals?.period || ""}`.trim();
};

const percentDelta = (value, baseline) => (baseline ? ((value - baseline) / baseline) * 100 : 0);

function bestMonth(year, key) {
  return monthsForYear(year)
    .filter((month) => month.days > 0)
    .reduce((best, month) => (!best || month[key] > best[key] ? month : best), null);
}

function setupTheme() {
  document.documentElement.dataset.theme = state.theme;
  el("themeToggle").addEventListener("click", () => {
    state.theme = state.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = state.theme;
    safeStorage.set("solar-theme", state.theme);
    renderCharts();
  });
}

function renderStaticInfo() {
  el("installationName").textContent = data.installation.name;
  el("sidePower").textContent = formatKwc(data.installation.power_kwc);
  el("sidePanels").textContent = formatNumber(data.installation.panel_count);
  el("sideCost").textContent = formatCurrency(data.installation.cost_eur);
  el("latestDate").textContent = `Dernière donnée ${formatDate(data.meta.latest_date)}`;
  el("generatedAt").textContent = `Généré ${formatDateTime(data.meta.generated_at)}`;
  if (el("versionBadge")) el("versionBadge").textContent = "v3";

  el("phaseList").innerHTML = `
    <p class="section-label">Phases</p>
    ${data.installation.phases
      .map(
        (phase) => `
          <div class="phase-item">
            <strong>${phase.name}</strong>
            <span>${formatKwc(phase.power_kwc)}</span>
            <small>${formatDate(phase.date)} · ${formatCurrency(phase.cost_eur)} · ${phase.orientation || "orientation --"}</small>
          </div>
        `,
      )
      .join("")}
  `;
}

function renderKpis() {
  const totals = data.totals;
  const projection = data.projections;
  const cards = [
    {
      label: "Économies réalisées",
      value: formatCurrency(totals.realized_savings_eur),
      sub: `${formatPercent(totals.amortization_percent)} de l'investissement`,
      color: "var(--accent)",
      tone: "accent",
    },
    {
      label: "Reste à amortir",
      value: formatCurrency(totals.remaining_payback_eur),
      sub: `Projection saisonnalisée : ${formatDate(projection.payback_seasonal_date || projection.payback_reference_date)}`,
      color: "var(--accent-2)",
      tone: "accent-2",
    },
    {
      label: "Production solaire",
      value: formatKwh(totals.production_kwh),
      sub: `${formatKwh(totals.autoconsumption_kwh)} autoconsommés`,
      color: "var(--solar)",
      tone: "solar",
    },
    {
      label: "Injection totale",
      value: formatKwh(totals.injection_kwh),
      sub: `${formatPercent(100 - totals.autoconsumption_percent)} de la production`,
      color: "var(--warn)",
      tone: "warn",
    },
    {
      label: "Facture nette",
      value: formatCurrency(totals.net_cost_eur),
      sub: `${formatCurrency(totals.resale_eur)} de revente déduite`,
      color: "var(--accent-3)",
      tone: "accent-3",
    },
  ];

  el("kpiGrid").innerHTML = cards
    .map(
      (card) => `
        <article class="kpi-card tone-${card.tone}">
          <span>${card.label}</span>
          <strong>${card.value}</strong>
          <small>${card.sub}</small>
        </article>
      `,
    )
    .join("");
}

function renderYearPickers() {
  const panels = [
    ["monthlyChart", "Année affichée"],
    ["paybackChart", "Année mise en évidence"],
    ["annualChart", "Année mise en évidence"],
    ["energyBalanceContent", "Année affichée"],
    ["phasePerformanceChart", "Année affichée"],
    ["yearTable", "Année mise en évidence"],
    ["monthlyConsumptionChart", "Année mise en évidence"],
    ["dailyChart", "Année affichée"],
    ["climateChart", "Année affichée"],
  ];
  panels.forEach(([id, label]) => {
    const panel = el(id).closest("article");
    if (panel.querySelector(".local-year-picker")) return;
    const picker = document.createElement("div");
    picker.className = "local-year-picker";
    picker.dataset.chart = id;
    picker.innerHTML = `<span>${label}</span><div class="year-tabs compact-year-tabs" role="group" aria-label="${label} — ${panel.querySelector('.section-label').textContent}" data-year-picker></div>`;
    panel.querySelector(".panel-header").after(picker);
  });
  const mainPicker = el("yearTabs");
  mainPicker.setAttribute("role", "group");
  mainPicker.setAttribute("aria-label", "Année du tableau de bord");
  const pickers = [mainPicker, ...document.querySelectorAll("[data-year-picker]")];
  pickers.forEach((picker) => {
    // Keep the buttons mounted so keyboard focus survives an update.
    if (!picker.querySelector("button")) {
      picker.innerHTML = data.years.map(({ year }) => `<button type="button" data-year="${year}">${year}</button>`).join("");
      picker.querySelectorAll("button").forEach((button) => {
        button.addEventListener("click", () => {
          const top = button.getBoundingClientRect().top;
          state.selectedYear = Number(button.dataset.year);
          state.highlightedYear = state.selectedYear;
          render();
          // Updating sections above this one must not move the reader away.
          window.scrollBy(0, button.getBoundingClientRect().top - top);
        });
      });
    }
    picker.querySelectorAll("button").forEach((button) => {
      const isMatrix = picker.closest('[data-chart="monthlyConsumptionChart"]');
      const selectedYear = isMatrix ? state.highlightedYear : state.selectedYear;
      const active = Number(button.dataset.year) === selectedYear;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  });
}

function renderControls() {
  renderYearPickers();

  el("metricSelect").value = state.metric;
  el("metricSelect").onchange = (event) => {
    state.metric = event.target.value;
    renderFocus();
    renderCharts();
  };

  el("dailyModeTabs").querySelectorAll("button").forEach((button) => {
    const isActive = button.dataset.mode === state.dailyMode;
    button.classList.toggle("active", isActive);
    button.onclick = () => {
      state.dailyMode = button.dataset.mode;
      renderControls();
      renderFocus();
      renderCharts();
    };
  });
}

function renderInsights() {
  const ref = referenceYear();
  const current = yearByValue(data.meta.latest_year);
  const selected = yearByValue(state.selectedYear);
  const bestProduction = bestMonth(ref.year, "production_kwh");
  const currentProjection = data.projections.current_seasonal_production_kwh || data.projections.current_annualized_production_kwh;
  const projectionDelta = percentDelta(currentProjection, ref.production_kwh);
  const selectedCost = selected.net_cost_eur + selected.resale_eur;

  const cards = [
    {
      label: "Lecture système",
      value: `${formatPercent(data.totals.amortization_percent)} amorti`,
      text: `${formatCurrency(data.totals.realized_savings_eur)} récupérés, ${formatCurrency(data.totals.remaining_payback_eur)} restent à couvrir.`,
    },
    {
      label: "Année repère",
      value: String(ref.year),
      text: `${formatKwh(ref.production_kwh)} produits, ${formatCurrency(ref.net_cost_eur)} de facture nette.`,
    },
    {
      label: "Tendance en cours",
      value: `${formatPercent(current.coverage_percent)} chargé`,
      text: `${data.projections.current_year} projeté avec saisonnalité : ${formatKwh(currentProjection)} (${formatSignedPercent(projectionDelta)} vs ${ref.year}).`,
    },
    {
      label: "Mois solaire fort",
      value: bestProduction ? bestProduction.label : "--",
      text: bestProduction
        ? `${formatKwh(bestProduction.production_kwh)} produits sur l'année repère.`
        : "Aucune donnée mensuelle exploitable.",
    },
    {
      label: "Année affichée",
      value: String(selected.year),
      text: `${formatCurrency(selectedCost)} brut, ${formatCurrency(selected.resale_eur)} de revente, ${formatCurrency(selected.net_cost_eur)} net.`,
    },
  ];

  el("insightGrid").innerHTML = cards
    .map(
      (card) => `
        <article class="insight-card">
          <span>${card.label}</span>
          <strong>${card.value}</strong>
          <small>${card.text}</small>
        </article>
      `,
    )
    .join("");
}

function renderQualityStrip() {
  const current = yearByValue(data.meta.latest_year);
  const ref = referenceYear();
  const checks = data.quality?.matrix_checks || [];
  const matrixOk = checks.length ? checks.every((item) => item.ok) : true;
  const completeYears = data.years
    .filter((year) => year.coverage_percent >= 99 && year.year >= data.meta.first_full_solar_year)
    .map((year) => year.year)
    .join(", ");
  const linkyCheck = state.linkyReconciliation;

  const items = [
    {
      label: "Source prioritaire",
      value: data.quality?.consumption_matrix_source || data.meta.source_file,
      text: `Généré le ${formatDateTime(data.meta.generated_at)}`,
    },
    {
      label: "Données à date",
      value: formatDate(data.meta.latest_date),
      text: `${current.filled_days} jours chargés · ${formatPercent(current.coverage_to_date_percent)} de la période attendue`,
    },
    {
      label: "Contrôle Excel",
      value: matrixOk ? "Cohérent" : "Écart détecté",
      text: matrixOk ? "Totaux mensuels et feuilles quotidiennes concordent." : "Voir le rapport d'audit pour le détail.",
    },
    {
      label: "Contrôle Linky / Excel",
      value: linkyCheck ? (linkyCheck.coherent ? `${linkyCheck.days} j cohérents` : "Écart détecté") : "En attente",
      text: linkyCheck
        ? `${formatDate(linkyCheck.start)} → ${formatDate(linkyCheck.end)} · écart ${formatNumber(linkyCheck.deltaKwh, 3)} kWh`
        : "Disponible dès que le service Linky local répond.",
    },
    {
      label: "Injection mensuelle",
      value: data.quality?.monthly_injection_is_estimated ? "Estimée" : "Mesurée",
      text: state.linky?.summary?.injection_kwh != null
        ? `Historique estimé; Linky mesure l'injection depuis le ${formatLinkyDate(state.linky.summary.injection_start || linkyCheck?.start || state.linky.last_data)}.`
        : data.quality?.monthly_injection_note || "--",
    },
    {
      label: "EDF OA",
      value: formatCurrency(data.oa?.invoice_2025_eur || ref.resale_eur),
      text: data.oa?.invoice_2025_start
        ? `${formatDate(data.oa.invoice_2025_start)} → ${formatDate(data.oa.invoice_2025_end)} · ${formatKwh(data.oa.invoice_2025_kwh)}`
        : `${formatKwh(ref.factured_resale_kwh)} facturés`,
    },
    {
      label: "Année repère",
      value: completeYears || String(ref.year),
      text: "Comparer en priorité les années complètes; une année en cours reste une tendance.",
    },
  ];

  el("qualityStrip").innerHTML = items
    .map(
      (item) => `
        <div class="quality-item">
          <span>${item.label}</span>
          <strong>${item.value}</strong>
          <small>${item.text}</small>
        </div>
      `,
    )
    .join("");
}

function climateEventColor(type) {
  const c = colors();
  return (
    {
      heat: c.climateHeat,
      cold: c.climateCold,
      rain: c.climateRain,
      dry: c.climateDry,
      wind: c.climateStorm,
    }[type] || c.accent
  );
}

const climateTone = (type) => ({ heat: "heat", cold: "cold", rain: "rain", dry: "dry", wind: "storm" }[type] || "accent");

function renderClimate() {
  const section = document.querySelector(".climate-section");
  if (!section) return;

  const year = weatherYearByValue(state.selectedYear) || latestWeatherYear();
  if (!weatherData || !year) {
    section.hidden = true;
    return;
  }

  section.hidden = false;
  const c = colors();
  const station = weatherData.station || {};
  const thresholds = weatherData.meta?.thresholds || {};
  const baseline = weatherData.normals?.period || "1991-2020";
  const status = year.status || (year.coverage_percent >= 95 ? "Année complète" : "En cours");
  const stationName = station.long_name || station.name || weatherData.meta?.station_id || "Station météo";

  el("climateTitle").textContent = `Climat ${year.year}`;
  el("climateStationStatus").textContent = `${station.name || "Station"} · ${formatDate(weatherData.meta?.latest_date)}`;

  const cards = [
    {
      label: "Canicule estimée",
      value: formatDays(year.estimated_hot_sequence_days),
      sub: `${year.estimated_hot_sequence_episodes || 0} séquence(s) · seuil local ≥ ${formatNumber(thresholds.hot_day_c || 30, 0)} °C sur ${thresholds.estimated_hot_sequence_min_days || 3} j`,
      color: c.climateHeat,
      tone: "heat",
    },
    {
      label: "Jours très chauds",
      value: formatDays(year.hot_days_30),
      sub: climateDeltaText(year, year.hot_days_30_delta, " j"),
      color: c.climateHeat,
      tone: "heat",
    },
    {
      label: "Froid",
      value: formatDays(year.frost_days),
      sub: `Min ${formatTemp(year.min_tn_c)} · ${climateDeltaText(year, year.frost_days_delta, " j")}`,
      color: c.climateCold,
      tone: "cold",
    },
    {
      label: "Pluie",
      value: formatMm(year.rain_total_mm),
      sub: `${formatDays(year.rain_days_1mm)} de pluie · ${climateDeltaText(year, year.rain_total_delta_mm, " mm")}`,
      color: c.climateRain,
      tone: "rain",
    },
    {
      label: "Sec",
      value: formatDays(year.longest_dry_spell_days),
      sub: formatDateRange(year.longest_dry_spell_start, year.longest_dry_spell_end),
      color: c.climateDry,
      tone: "dry",
    },
    {
      label: "Vent",
      value: formatKmh(year.wind_gust_max_kmh),
      sub: year.wind_gust_max_date ? `${formatDays(year.windy_days_60kmh)} ≥ 60 km/h · ${formatDate(year.wind_gust_max_date)}` : "Rafales non disponibles",
      color: c.climateStorm,
      tone: "storm",
    },
  ];

  el("climateKpiGrid").innerHTML = cards
    .map(
      (card) => `
        <div class="climate-stat tone-${card.tone}">
          <span>${card.label}</span>
          <strong>${card.value}</strong>
          <small>${card.sub}</small>
        </div>
      `,
    )
    .join("");

  const events = Array.isArray(year.events) ? year.events : [];
  el("climateEvents").innerHTML = `
    <h4>${stationName}</h4>
    <p>${status} · ${year.filled_days} / ${year.expected_days} jours · normale ${baseline}</p>
    <ul>
      ${events
        .map(
          (event) => `
            <li class="tone-${climateTone(event.type)}">
              <span>
                <strong>${event.label} · ${event.value}</strong>
                ${formatDateRange(event.date, event.end_date)}
              </span>
            </li>
          `,
        )
        .join("")}
    </ul>
    <p>Les séquences chaudes sont un indicateur local estimé, utile pour l'analyse solaire, pas une alerte officielle Météo-France.</p>
  `;
  renderWeatherComparison();
}

function renderWeatherComparison() {
  const table = el("weatherComparisonTable");
  const analysis = el("weatherAnalysis");
  const caution = el("weatherCaution");
  if (!table || !analysis || !caution || !weatherData?.years?.length) return;

  const energyYears = new Map(data.years.map((item) => [Number(item.year), item]));
  const rows = weatherData.years.map((weatherYear) => ({ weather: weatherYear, energy: energyYears.get(Number(weatherYear.year)) })).filter((row) => row.energy);
  table.innerHTML = rows.map((row, index) => {
    const { weather, energy } = row;
    const complete = weather.coverage_percent >= 99 && energy.coverage_percent >= 99 && !energy.is_current_year;
    const previous = index > 0 ? rows[index - 1] : null;
    const comparableEvolution = complete && previous && previous.weather.coverage_percent >= 99 && previous.energy.coverage_percent >= 99;
    const evolution = comparableEvolution ? percentDelta(energy.actual_home_consumption_kwh, previous.energy.actual_home_consumption_kwh) : null;
    return `<tr class="${complete ? "year-complete" : "year-current"}"><td><strong>${weather.year}</strong><span class="year-scope">${complete ? "Complète" : "En cours"}</span></td><td>${complete ? `${weather.filled_days} jours` : `${weather.filled_days} / ${weather.expected_days} jours`}</td><td>${formatTemp(weather.avg_tm_c)}</td><td>${formatMm(weather.rain_total_mm, 1)}</td><td>${formatDays(weather.hot_days_30)}</td><td>${formatDays(weather.frost_days)}</td><td><strong>${formatKwh(energy.actual_home_consumption_kwh)}</strong></td><td>${evolution == null ? (complete ? "Base" : "Non annualisée") : formatSignedPercent(evolution)}</td></tr>`;
  }).join("");

  const currentYear = data.meta.latest_year;
  const referenceYear = data.projections.reference_year;
  const latestMonth = new Date(`${data.meta.latest_date}T00:00:00`).getMonth() + 1;
  const completeMonths = Math.max(1, latestMonth - 1);
  const energyPeriod = (year) => (data.months?.[String(year)] || []).slice(0, completeMonths).reduce((totals, month) => ({ consumption: totals.consumption + Number(month.consumption_kwh || 0), production: totals.production + Number(month.production_kwh || 0) }), { consumption: 0, production: 0 });
  const weatherPeriod = (year) => {
    const months = (weatherYearByValue(year)?.months || []).slice(0, completeMonths);
    const days = months.reduce((sum, month) => sum + Number(month.filled_days || 0), 0);
    return { temperature: days ? months.reduce((sum, month) => sum + Number(month.avg_tm_c || 0) * Number(month.filled_days || 0), 0) / days : null, rain: months.reduce((sum, month) => sum + Number(month.rain_total_mm || 0), 0), hot: months.reduce((sum, month) => sum + Number(month.hot_days_30 || 0), 0), frost: months.reduce((sum, month) => sum + Number(month.frost_days || 0), 0) };
  };
  const currentEnergy = energyPeriod(currentYear);
  const referenceEnergy = energyPeriod(referenceYear);
  const currentWeather = weatherPeriod(currentYear);
  const referenceWeather = weatherPeriod(referenceYear);
  const consumptionDelta = percentDelta(currentEnergy.consumption, referenceEnergy.consumption);
  const productionDelta = percentDelta(currentEnergy.production, referenceEnergy.production);
  const temperatureDelta = currentWeather.temperature - referenceWeather.temperature;
  const rainDelta = percentDelta(currentWeather.rain, referenceWeather.rain);
  const hotDelta = currentWeather.hot - referenceWeather.hot;
  const frostDelta = currentWeather.frost - referenceWeather.frost;
  const lastCompleteMonth = DEFAULT_MONTH_LABELS[completeMonths - 1].toLowerCase();

  const full2024 = rows.find((row) => row.weather.year === 2024);
  const full2025 = rows.find((row) => row.weather.year === 2025);
  const stableNeedDelta = full2024 && full2025 ? percentDelta(full2025.energy.actual_home_consumption_kwh, full2024.energy.actual_home_consumption_kwh) : null;
  const fullTempDelta = full2024 && full2025 ? full2025.weather.avg_tm_c - full2024.weather.avg_tm_c : null;

  analysis.innerHTML = `
    <article><span class="analysis-kicker">Même période · janvier–${lastCompleteMonth}</span><strong>Prélèvement réseau ${formatSignedPercent(consumptionDelta)}</strong><p>Entre ${referenceYear} et ${currentYear}, la température moyenne monte de ${formatSignedValue(temperatureDelta, " °C", 1)}, avec ${formatSignedValue(hotDelta, " j", 0)} de forte chaleur et ${formatSignedValue(frostDelta, " j", 0)} de gel. La production solaire évolue de ${formatSignedPercent(productionDelta)}, ce qui peut masquer une partie des usages dans le prélèvement réseau.</p></article>
    <article><span class="analysis-kicker">Années complètes · 2024 → 2025</span><strong>Besoin maison ${stableNeedDelta == null ? "--" : formatSignedPercent(stableNeedDelta)}</strong><p>Le besoin électrique reconstitué reste presque stable alors que la température moyenne varie de ${fullTempDelta == null ? "--" : formatSignedValue(fullTempDelta, " °C", 1)}. Sur ces deux années, aucun effet météo massif n'apparaît dans le total annuel.</p></article>
    <article><span class="analysis-kicker">Pluie et saison chaude</span><strong>${formatSignedPercent(rainDelta)} de pluie à période égale</strong><p>${currentYear} cumule ${formatDays(currentWeather.hot)} de forte chaleur contre ${formatDays(referenceWeather.hot)} en ${referenceYear}. Cela peut accroître certains usages estivaux, mais les données ne séparent pas la piscine, la climatisation éventuelle et les autres changements d'habitude.</p></article>
  `;
  caution.innerHTML = `<strong>Conclusion prudente.</strong> La météo peut contribuer aux écarts mensuels, surtout par le chauffage, la filtration et les usages d'été. Elle n'explique pas seule l'évolution observée : les deux installations solaires ont démarré à des dates différentes, l'autoconsommation réduit le prélèvement Linky et les habitudes du foyer ne sont pas mesurées séparément. Le rapprochement est un indice, pas une preuve de causalité.`;
}

function renderStrategy() {
  const year = yearByValue(state.selectedYear);
  const ref = referenceYear();
  const pool = data.pool || {};
  const plugPhase = data.installation.phases?.[0] || {};
  const mainPhase = data.installation.phases?.[1] || {};

  el("energyBalanceTitle").textContent = `${year.year} · ${formatStatusLabel(year.status)}`;
  const balancePeriodLabel = year.is_current_year ? "à date" : "annuel";
  el("energyBalanceStatus").textContent = year.energy_balance_percent >= 100
    ? `Bilan ${balancePeriodLabel} +${formatNumber(year.energy_balance_percent - 100, 1)} %`
    : `Couverture ${balancePeriodLabel} ${formatPercent(year.energy_balance_percent)}`;
  el("energyBalanceContent").innerHTML = `
    <div class="summary-row"><span>Besoin électrique réel</span><strong>${formatKwh(year.actual_home_consumption_kwh)}</strong></div>
    <div class="summary-row"><span>Production photovoltaïque</span><strong>${formatKwh(year.production_kwh)}</strong></div>
    <div class="summary-row"><span>Taux d'autonomie électrique</span><strong>${formatPercent(year.autonomy_percent)}</strong></div>
    <div class="summary-row"><span>Taux d'autoconsommation</span><strong>${formatPercent(year.autoconsumption_percent)}</strong></div>
    <div class="summary-row"><span>Solde énergétique ${balancePeriodLabel}</span><strong>${formatSignedValue(year.net_energy_balance_kwh, " kWh", 0)}</strong></div>
    <p class="strategy-note">Le bilan annuel ne signifie pas autonomie 24/7 : les périodes de production et de consommation ne coïncident pas toujours.</p>
  `;

  if (year.production_split_available && year.specific_yield_plug_kwh_kwc != null && year.specific_yield_main_kwh_kwc != null && year.specific_yield_main_kwh_kwc > 0) {
    const performancePeriod = year.is_current_year
      ? `cumul du ${formatDate(year.first_date)} au ${formatDate(year.last_date)}`
      : "année complète";
    el("phasePerformanceStatus").textContent = `${formatPercent(year.plug_vs_main_yield_percent)} du rendement toiture · ${year.is_current_year ? "à date" : "année complète"}`;
    const delta = year.plug_vs_main_yield_percent - 100;
    el("phasePerformanceNote").innerHTML = `
      <strong>${year.year} · ${performancePeriod}</strong><br>
      Colonne G — P&P ${formatKwc(plugPhase.power_kwc)} : ${formatKwh(year.production_plug_kwh)} ÷ ${formatNumber(plugPhase.power_kwc, 2)} =
      <strong>${formatNumber(year.specific_yield_plug_kwh_kwc, 1)} kWh/kWc</strong>.<br>
      Colonne H — toiture ${formatKwc(mainPhase.power_kwc)} : ${formatKwh(year.production_main_kwh)} ÷ ${formatNumber(mainPhase.power_kwc, 2)} =
      <strong>${formatNumber(year.specific_yield_main_kwh_kwc, 1)} kWh/kWc</strong>.<br>
      Le ratio ${formatPercent(year.plug_vs_main_yield_percent)} compare les rendements ramenés à 1 kWc, pas les productions brutes. Écart ${formatSignedPercent(delta)}.
    `;
  } else {
    el("phasePerformanceStatus").textContent = "Séparation indisponible";
    el("phasePerformanceNote").textContent = "Cette année ne sépare pas proprement les deux installations dans les données sources.";
  }

  el("poolStrategyContent").innerHTML = `
    <div class="summary-row"><span>Volume estimé</span><strong>${formatNumber(pool.volume_m3_est, 1)} m³</strong></div>
    <div class="summary-row"><span>Pompe</span><strong>${formatNumber(pool.pump_power_w)} W</strong></div>
    <div class="summary-row"><span>Filtration estivale type</span><strong>${formatNumber(pool.summer_runtime_low_h, 0)}–${formatNumber(pool.summer_runtime_high_h, 0)} h/j</strong></div>
    <div class="summary-row"><span>Énergie/jour type</span><strong>${formatNumber(pool.summer_daily_kwh_low, 1)}–${formatNumber(pool.summer_daily_kwh_high, 1)} kWh</strong></div>
    <div class="summary-row"><span>P&P sur année repère ${ref.year}</span><strong>${ref.production_plug_kwh != null ? formatKwh(ref.production_plug_kwh) : "--"}</strong></div>
    <div class="summary-row"><span>Équivalent théorique filtration</span><strong>${pool.equivalent_pump_days_low ? `${formatNumber(pool.equivalent_pump_days_low)}–${formatNumber(pool.equivalent_pump_days_high)} j` : "--"}</strong></div>
    <p class="strategy-note">${pool.note || ""} Le P&P a été installé d'abord pour absorber le surcoût de la piscine; la toiture 3 kWc est venue ensuite après validation du principe.</p>
  `;
}

function renderFocus() {
  const year = yearByValue(state.selectedYear);
  el("selectedYearTitle").textContent = `${year.year} - ${formatStatusLabel(year.status)}`;
  el("selectedYearStatus").textContent = year.is_current_year
    ? `${formatPercent(year.coverage_percent)} chargé`
    : formatStatusLabel(year.status);
  el("dailyChartTitle").textContent =
    state.dailyMode === "recent" ? `${year.year} - dernières mesures` : `${year.year} jour par jour`;

  el("focusSummary").innerHTML = `
    <div class="summary-row"><span>Jours chargés</span><strong>${year.filled_days} / ${year.year_days}</strong></div>
    <div class="summary-row"><span>Production</span><strong>${formatKwh(year.production_kwh)}</strong></div>
    <div class="summary-row"><span>Consommation réseau</span><strong>${formatKwh(year.consumption_kwh)}</strong></div>
    <div class="summary-row"><span>Consommation réelle maison</span><strong>${formatKwh(year.actual_home_consumption_kwh)}</strong></div>
    <div class="summary-row"><span>Autoconsommation solaire</span><strong>${formatPercent(year.autoconsumption_percent)}</strong></div>
    <div class="summary-row"><span>Autonomie électrique</span><strong>${formatPercent(year.autonomy_percent)}</strong></div>
    <div class="summary-row"><span>${year.is_current_year ? "Équilibre prod./besoin à date" : "Équilibre annuel prod./besoin"}</span><strong>${formatPercent(year.energy_balance_percent)}</strong></div>
    <div class="summary-row"><span>Économies réalisées</span><strong>${formatCurrency(year.realized_savings_eur)}</strong></div>
    <div class="summary-row"><span>Prix moyen kWh réseau</span><strong>${formatCurrency(year.energy_price_eur_kwh, 3)}</strong></div>
    <div class="summary-row"><span>Facture nette</span><strong>${formatCurrency(year.net_cost_eur)}</strong></div>
  `;
}

function renderTable() {
  el("yearTable").innerHTML = data.years
    .map(
      (year) => `
        <tr data-year="${year.year}" class="${year.year === state.selectedYear ? "active" : ""}">
          <td><strong>${year.year}</strong></td>
          <td><span class="year-badge">${formatStatusLabel(year.status)}</span></td>
          <td>${formatKwh(year.production_kwh)}</td>
          <td>${formatKwh(year.consumption_kwh)}</td>
          <td>${formatCurrency(year.realized_savings_eur)}</td>
          <td>${formatCurrency(year.net_cost_eur)}</td>
          <td>${formatCurrency(year.cumulative_savings_eur)}</td>
        </tr>
      `,
    )
    .join("");

  el("yearTable").querySelectorAll("tr").forEach((row) => {
    row.addEventListener("click", () => {
      state.selectedYear = Number(row.dataset.year);
      state.highlightedYear = state.selectedYear;
      render();
    });
  });
}

function consumptionLevel(value, minValue, maxValue) {
  if (!value || maxValue <= minValue) return "level-1";
  const ratio = (value - minValue) / (maxValue - minValue);
  if (ratio >= 0.75) return "level-4";
  if (ratio >= 0.5) return "level-3";
  if (ratio >= 0.25) return "level-2";
  return "level-1";
}

function renderMonthlyConsumptionTable() {
  const labels = monthLabels();
  const rows = monthlyConsumptionRows();
  const values = rows
    .flatMap((row) => row.months)
    .filter(hasMonthData)
    .map((month) => month.consumption_kwh)
    .filter((value) => value > 0);
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const selectedRow = rows.find((row) => row.year === state.highlightedYear);
  const selectedTotal = selectedRow && selectedRow.total_kwh != null ? selectedRow.total_kwh : 0;

  el("monthlyConsumptionStatus").textContent =
    selectedRow && selectedRow.total_kwh != null
      ? `${state.highlightedYear} : ${formatKwh(selectedTotal)}`
      : `${state.highlightedYear} : --`;
  el("monthlyConsumptionHead").innerHTML = `
    <tr>
      <th>Année</th>
      ${labels.map((label) => `<th>${label}</th>`).join("")}
      <th>Total</th>
      <th>Moy./mois</th>
    </tr>
  `;

  el("monthlyConsumptionTable").innerHTML = rows
    .map((row) => {
      const cells = labels
        .map((label, index) => {
          const month = row.months[index];
          if (!hasMonthData(month)) {
            return `<td class="month-kwh-cell empty" title="${label} ${row.year} : aucune donnée">--</td>`;
          }
          const level = consumptionLevel(month.consumption_kwh, minValue, maxValue);
          return `
            <td class="month-kwh-cell ${level}" title="${label} ${row.year} : ${formatKwh(month.consumption_kwh, 2)}">
              ${formatNumber(month.consumption_kwh, 2)}
            </td>
          `;
        })
        .join("");

      return `
        <tr
          data-year="${row.year}"
          data-selectable="${row.isSelectable ? "true" : "false"}"
          class="${row.year === state.highlightedYear ? "active" : ""} ${row.isSelectable ? "" : "muted-row"}"
        >
          <td>
            <span class="year-badge">${row.year}</span>
            <small class="matrix-year-status">${row.status}</small>
          </td>
          ${cells}
          <td class="matrix-total-cell">${row.total_kwh != null ? formatNumber(row.total_kwh, 2) : "--"}</td>
          <td>${row.average_month_kwh != null ? formatNumber(row.average_month_kwh, 2) : "--"}</td>
        </tr>
      `;
    })
    .join("");

  el("monthlyConsumptionTable").querySelectorAll("tr").forEach((row) => {
    row.addEventListener("click", () => {
      const year = Number(row.dataset.year);
      state.highlightedYear = year;
      if (row.dataset.selectable === "true") {
        state.selectedYear = year;
      }
      render();
    });
  });
}

function renderProjection() {
  const projection = data.projections;
  const totals = data.totals;
  const hasNumber = (value) => typeof value === "number" && Number.isFinite(value);
  const duration = projection.total_payback_duration_seasonal_years;
  const remaining = projection.years_remaining_seasonal;
  const percent = hasNumber(totals.amortization_percent)
    ? Math.max(0, Math.min(totals.amortization_percent, 100)) : null;
  const years = (value) => hasNumber(value) && value >= 0 ? `${formatNumber(value, 1)} ans` : "Non estimable";
  el("cumulativeScope").textContent = `Du ${formatDate(data.meta.first_install_date)} au ${formatDate(data.meta.latest_date)} · toutes les années cumulées.`;
  el("projectionContent").innerHTML = `
    <div class="payback-overview">
      <div class="payback-horizon payback-primary">
        <span class="payback-label">Temps restant estimé</span>
        <strong class="payback-number">${years(remaining)}</strong>
        <p>À partir des données du ${formatDate(data.meta.latest_date)}.</p>
        <span class="payback-date">Échéance estimée : <b>${formatDate(projection.payback_seasonal_date)}</b></span>
      </div>
      <div class="payback-duration">
        <span class="payback-label">Durée totale estimée</span>
        <strong>${years(duration)}</strong>
        <p>Du point de départ économique pondéré jusqu’à l’échéance.</p>
      </div>
      <div class="payback-progress">
        <div class="payback-progress-label"><span>Investissement récupéré</span><strong>${percent === null ? "Non disponible" : formatPercent(totals.amortization_percent)}</strong></div>
        ${percent === null ? '<p>Progression indisponible.</p>' : `<progress class="payback-meter" max="100" value="${percent}" aria-label="Part de l’investissement amortie">${formatPercent(percent)}</progress>`}
        <div class="payback-money"><span><b>${formatCurrency(totals.realized_savings_eur)}</b> récupérés</span><span><b>${formatCurrency(totals.remaining_payback_eur)}</b> à couvrir</span></div>
        <p>Sur ${formatCurrency(data.installation.cost_eur)} investis. La barre suit les euros récupérés.</p>
      </div>
    </div>
    <div class="payback-footer"><span>Projection saisonnalisée · estimation, pas une date garantie.</span><a class="text-link" href="#/amortissement">Voir le calcul détaillé →</a></div>
  `;
  el("projectionDetails").innerHTML = `
    <div class="projection-detail-grid">
    <div><h4>Hypothèses annuelles</h4>
    <div class="projection-row"><span>Référence ${projection.reference_year}</span><strong>${formatCurrency(projection.reference_savings_eur)} / an</strong></div>
    <div class="projection-row"><span>${projection.current_year} saisonnalisé</span><strong>${formatCurrency(projection.current_seasonal_savings_eur)} / an</strong></div>
    <div class="projection-row"><span>Production ${projection.current_year} projetée</span><strong>${formatKwh(projection.current_seasonal_production_kwh)}</strong></div>
    </div>
    <div><h4>Dates et durée</h4>
    <div class="projection-row">
      <span>Date estimée (saisonnalisée)</span>
      <strong>${formatDate(projection.payback_seasonal_date)}</strong>
    </div>
    <div class="projection-row">
      <span>Scénario référence ${projection.reference_year}</span>
      <strong>${formatDate(projection.payback_reference_date)}</strong>
    </div>
    <div class="projection-row">
      <span>Durée économique pondérée</span>
      <strong>${years(duration)}</strong>
    </div>
    <div class="projection-row"><span>Date d’investissement pondérée</span><strong>${formatDate(projection.weighted_investment_date)}</strong></div>
    </div>
    </div>
    <p class="projection-note">La durée totale part de la date d’investissement pondérée par les montants engagés, et non de la première pose. Le temps restant part de la dernière donnée disponible.</p>
    <p class="projection-note">
      ${projection.method} L'ancienne annualisation linéaire aurait donné ${formatKwh(projection.current_linear_production_kwh)} : elle est conservée pour audit mais n'est plus utilisée comme scénario principal.
    </p>
  `;
  const timeline = el("investmentTimeline");
  if (timeline) {
    timeline.innerHTML = `${data.installation.phases.map((phase, index) => `<article><span class="timeline-index">0${index + 1}</span><div><small>${formatDate(phase.date)}</small><strong>${phase.name} · ${formatKwc(phase.power_kwc)}</strong><p>${formatCurrency(phase.cost_eur)} engagés · ${phase.orientation}</p></div></article>`).join("")}<article class="timeline-result"><span class="timeline-index">Σ</span><div><small>Point de départ économique</small><strong>${formatDate(projection.weighted_investment_date)}</strong><p>Date pondérée par les montants, utilisée pour la durée totale.</p></div></article>`;
  }
}

function setupCanvas(canvas) {
  const previousLegend = canvas.nextElementSibling;
  if (previousLegend?.classList.contains("chart-legend")) previousLegend.hidden = true;
  const ratio = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(320, rect.width);
  const height = Number(canvas.getAttribute("height")) || 260;
  canvas.width = Math.floor(width * ratio);
  canvas.height = Math.floor(height * ratio);
  canvas.style.height = `${height}px`;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  return { ctx, width, height };
}

function drawGrid(ctx, plot, maxValue, steps = 4) {
  const c = colors();
  ctx.strokeStyle = c.border;
  ctx.lineWidth = 1;
  ctx.fillStyle = c.muted;
  ctx.font = "12px Segoe UI, Arial, sans-serif";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";

  for (let i = 0; i <= steps; i += 1) {
    const y = plot.bottom - (plot.height * i) / steps;
    ctx.beginPath();
    ctx.moveTo(plot.left, y);
    ctx.lineTo(plot.right, y);
    ctx.stroke();
    const label = maxValue >= 1000 ? `${formatNumber((maxValue * i) / steps / 1000, 1)}k` : formatNumber((maxValue * i) / steps, 0);
    ctx.fillText(label, plot.left - 10, y);
  }
}

function drawLegend(ctx, items, x, y, options = {}) {
  const canvas = ctx.canvas;
  let legend = canvas.nextElementSibling;
  if (!legend || !legend.classList.contains("chart-legend")) {
    legend = document.createElement("div");
    legend.className = "chart-legend";
    legend.setAttribute("role", "list");
    legend.setAttribute("aria-label", "Légende du graphique");
    canvas.after(legend);
  }
  legend.replaceChildren();
  legend.hidden = false;
  const highlighted = options.highlightLabels || [];
  items.forEach((item) => {
    const entry = document.createElement("span");
    const active = !highlighted.length || highlighted.includes(item.label);
    entry.className = "chart-legend-item " + (active ? "is-highlighted" : "is-secondary");
    entry.setAttribute("role", "listitem");
    const swatch = document.createElement("i");
    swatch.className = "chart-legend-swatch";
    swatch.style.backgroundColor = item.color;
    swatch.setAttribute("aria-hidden", "true");
    entry.append(swatch, document.createTextNode(item.label));
    legend.append(entry);
  });
}

function roundRect(ctx, x, y, width, height, radius) {
  const r = Math.min(radius, width / 2, Math.abs(height) / 2);
  const top = height < 0 ? y + height : y;
  const h = Math.abs(height);
  ctx.beginPath();
  ctx.moveTo(x + r, top);
  ctx.arcTo(x + width, top, x + width, top + h, r);
  ctx.arcTo(x + width, top + h, x, top + h, r);
  ctx.arcTo(x, top + h, x, top, r);
  ctx.arcTo(x, top, x + width, top, r);
  ctx.closePath();
}

function drawBarChart(canvas, labels, series, options = {}) {
  const { ctx, width, height } = setupCanvas(canvas);
  const c = colors();
  const isDark = document.documentElement.dataset.theme === "dark";
  const bottomPadding = options.bottomPadding || 66;
  const legendBottomOffset = options.legendBottomOffset || 14;
  const topPadding = options.topPadding || 22;
  const maxValuePadding = options.maxValuePadding || 1.16;
  const plot = {
    left: 52,
    right: width - 20,
    top: topPadding,
    bottom: height - bottomPadding,
  };
  plot.width = plot.right - plot.left;
  plot.height = plot.bottom - plot.top;
  const maxValue = Math.max(1, ...series.flatMap((item) => item.values.map((value) => Number(value || 0)))) * maxValuePadding;
  drawGrid(ctx, plot, maxValue);

  const groupWidth = plot.width / labels.length;
  const barWidth = Math.max(8, Math.min(24, (groupWidth - 14) / series.length));
  const highlightedLabels = options.highlightSeriesLabels || [];
  const hasSeriesHighlight = highlightedLabels.length > 0;
  const hasGroupHighlight = Number.isInteger(options.highlightIndex) && options.highlightIndex >= 0;
  const hoverRegions = [];

  if (hasGroupHighlight && options.highlightIndex < labels.length) {
    const bandX = plot.left + groupWidth * options.highlightIndex + 4;
    ctx.save();
    ctx.globalAlpha = isDark ? 0.16 : 0.1;
    ctx.fillStyle = c.accent;
    roundRect(ctx, bandX, plot.top, Math.max(groupWidth - 8, 8), plot.height, 6);
    ctx.fill();
    ctx.restore();
  }

  labels.forEach((label, index) => {
    const center = plot.left + groupWidth * index + groupWidth / 2;
    series.forEach((item, seriesIndex) => {
      const value = Number(item.values[index] || 0);
      const barHeight = (value / maxValue) * plot.height;
      const x = center - (barWidth * series.length) / 2 + seriesIndex * barWidth + seriesIndex * 3;
      const y = plot.bottom - barHeight;
      const isHighlightedSeries = !hasSeriesHighlight || highlightedLabels.includes(item.label);
      const isHighlightedGroup = !hasGroupHighlight || index === options.highlightIndex;
      const isHighlighted = isHighlightedSeries && isHighlightedGroup;
      const shouldDim = !isHighlightedSeries || !isHighlightedGroup;
      ctx.fillStyle = item.color;
      ctx.globalAlpha = shouldDim ? (isDark ? 0.24 : 0.34) : 1;
      ctx.shadowColor = isDark && isHighlighted ? item.color : "transparent";
      ctx.shadowBlur = isDark && isHighlighted ? 3 : 0;
      roundRect(ctx, x, y, barWidth, barHeight, 4);
      ctx.fill();
      if (isHighlighted && (hasSeriesHighlight || hasGroupHighlight)) {
        ctx.globalAlpha = isDark ? 0.92 : 0.78;
        ctx.strokeStyle = isDark ? "#EAF8FF" : c.text;
        ctx.lineWidth = 1.4;
        ctx.stroke();
      }
      if (isHighlighted && hasSeriesHighlight && value === 0) {
        ctx.globalAlpha = 1;
        ctx.fillStyle = item.color;
        ctx.shadowColor = isDark ? item.color : "transparent";
        ctx.shadowBlur = isDark ? 10 : 0;
        roundRect(ctx, x, plot.bottom - 3, barWidth, 3, 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
      ctx.shadowBlur = 0;
      hoverRegions.push({
        x,
        y,
        width: barWidth,
        height: barHeight,
        label,
        title: item.label,
        value,
        unit: options.unit || "",
      });
    });

    ctx.fillStyle = c.muted;
    ctx.font = "12px Segoe UI, Arial, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.fillText(options.shortLabels === false ? label : label.slice(0, 3), center, plot.bottom + 12);
  });

  drawLegend(ctx, series, plot.left, height - legendBottomOffset, { highlightLabels: highlightedLabels });
  bindTooltip(canvas, hoverRegions, (item) => {
    const value = formatChartValue(item.value, item.unit || options.unit);
    return `<strong>${item.label}</strong>${item.title}: ${value}`;
  });
}

function drawLineChart(canvas, labels, series, options = {}) {
  const { ctx, width, height } = setupCanvas(canvas);
  const c = colors();
  const isDark = document.documentElement.dataset.theme === "dark";
  const bottomPadding = options.bottomPadding || 66;
  const legendBottomOffset = options.legendBottomOffset || 14;
  const plot = {
    left: 52,
    right: width - 20,
    top: 22,
    bottom: height - bottomPadding,
  };
  plot.width = plot.right - plot.left;
  plot.height = plot.bottom - plot.top;
  const values = series.flatMap((item) => item.values.map((value) => Number(value || 0)));
  const maxValue = Math.max(1, ...values) * 1.14;
  drawGrid(ctx, plot, maxValue);

  const pointsForTooltip = [];

  series.forEach((item) => {
    ctx.strokeStyle = item.color;
    ctx.lineWidth = 2.4;
    ctx.shadowColor = isDark ? item.color : "transparent";
    ctx.shadowBlur = isDark ? 3 : 0;
    ctx.beginPath();
    item.values.forEach((raw, index) => {
      const value = Number(raw || 0);
      const x = plot.left + (plot.width * index) / Math.max(item.values.length - 1, 1);
      const y = plot.bottom - (value / maxValue) * plot.height;
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
      pointsForTooltip.push({ x, y, label: labels[index], title: item.label, value, color: item.color });
    });
    ctx.stroke();
    ctx.shadowBlur = 0;
  });

  ctx.fillStyle = c.muted;
  ctx.font = "12px Segoe UI, Arial, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  const labelStep = Math.max(1, Math.ceil(labels.length / 8));
  labels.forEach((label, index) => {
    if (index % labelStep !== 0 && index !== labels.length - 1) return;
    const x = plot.left + (plot.width * index) / Math.max(labels.length - 1, 1);
    ctx.fillText(label, x, plot.bottom + 12);
  });
  drawLegend(ctx, series, plot.left, height - legendBottomOffset);

  bindTooltip(canvas, pointsForTooltip, (item) => {
    const value = formatChartValue(item.value, options.unit || "kwh-precise");
    return `<strong>${item.label}</strong>${item.title}: ${value}`;
  }, true);
}

function drawPaybackChart() {
  const canvas = el("paybackChart");
  const { ctx, width, height } = setupCanvas(canvas);
  const c = colors();
  const isDark = document.documentElement.dataset.theme === "dark";
  const plot = { left: 52, right: width - 20, top: 22, bottom: height - 66 };
  plot.width = plot.right - plot.left;
  plot.height = plot.bottom - plot.top;

  const actualMap = new Map(data.years.map((year) => [year.year, year.cumulative_savings_eur]));
  const forecastMap = new Map((data.projections.forecast_path || []).map((item) => [item.year, item.cumulative_savings_eur]));
  const allYears = [...new Set([...actualMap.keys(), ...forecastMap.keys()])].sort((a, b) => a - b);
  const labels = allYears.map(String);
  const actualValues = allYears.map((year) => (actualMap.has(year) ? actualMap.get(year) : null));
  const forecastValues = allYears.map((year) => (forecastMap.has(year) ? forecastMap.get(year) : null));
  const costValues = allYears.map(() => data.installation.cost_eur);
  const maxValue = Math.max(
    data.installation.cost_eur,
    ...actualValues.filter((v) => v != null),
    ...forecastValues.filter((v) => v != null),
  ) * 1.1;
  drawGrid(ctx, plot, maxValue);

  drawLineChartRaw(ctx, plot, labels, [
    { label: "Économies cumulées", values: actualValues, color: c.accent },
    { label: "Projection", values: forecastValues, color: c.good, dash: [6, 5] },
    { label: "Investissement", values: costValues, color: c.solar },
  ], maxValue);

  const selectedIndex = allYears.findIndex((year) => year === state.selectedYear);
  if (selectedIndex >= 0) {
    const x = plot.left + (plot.width * selectedIndex) / Math.max(labels.length - 1, 1);
    ctx.save();
    ctx.strokeStyle = c.accent;
    ctx.lineWidth = 1.4;
    ctx.shadowColor = isDark ? c.accent : "transparent";
    ctx.shadowBlur = isDark ? 10 : 0;
    ctx.setLineDash([4, 5]);
    ctx.beginPath();
    ctx.moveTo(x, plot.top);
    ctx.lineTo(x, plot.bottom);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = isDark ? "#EAF8FF" : c.text;
    ctx.font = "700 12px Segoe UI, Arial, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "bottom";
    ctx.fillText(String(state.selectedYear), x, plot.top - 4);
    ctx.restore();
  }

  drawLegend(ctx, [
    { label: "Économies cumulées", color: c.accent },
    { label: "Projection", color: c.good },
    { label: "Investissement", color: c.solar },
  ], plot.left, height - 14);
}

function drawLineChartRaw(ctx, plot, labels, series, maxValue) {
  const c = colors();
  const isDark = document.documentElement.dataset.theme === "dark";
  series.forEach((item) => {
    ctx.strokeStyle = item.color;
    ctx.lineWidth = 2.5;
    ctx.shadowColor = isDark ? item.color : "transparent";
    ctx.shadowBlur = isDark ? 3 : 0;
    ctx.setLineDash(item.dash || []);
    ctx.beginPath();
    let started = false;
    item.values.forEach((value, index) => {
      if (value == null || Number.isNaN(Number(value))) {
        started = false;
        return;
      }
      const x = plot.left + (plot.width * index) / Math.max(item.values.length - 1, 1);
      const y = plot.bottom - (Number(value) / maxValue) * plot.height;
      if (!started) { ctx.moveTo(x, y); started = true; }
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.shadowBlur = 0;
  });
  ctx.fillStyle = c.muted;
  ctx.font = "12px Segoe UI, Arial, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  labels.forEach((label, index) => {
    const x = plot.left + (plot.width * index) / Math.max(labels.length - 1, 1);
    ctx.fillText(label, x, plot.bottom + 12);
  });
}

function drawPhasePerformanceChart() {
  const canvas = el("phasePerformanceChart");
  if (!canvas) return;
  const year = yearByValue(state.selectedYear);
  const c = colors();
  if (!year || !year.production_split_available || year.specific_yield_plug_kwh_kwc == null || year.specific_yield_main_kwh_kwc == null || year.specific_yield_main_kwh_kwc <= 0) {
    const { ctx, width, height } = setupCanvas(canvas);
    ctx.fillStyle = c.muted;
    ctx.font = "13px Segoe UI, Arial, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("Séparation des deux installations indisponible pour cette année", width / 2, height / 2);
    return;
  }
  const plugPhase = data.installation.phases?.[0] || {};
  const mainPhase = data.installation.phases?.[1] || {};
  drawBarChart(
    canvas,
    [`G · P&P ${formatNumber(plugPhase.power_kwc, 2)}`, `H · Toit ${formatNumber(mainPhase.power_kwc, 2)}`],
    [{
      label: "kWh/kWc",
      values: [year.specific_yield_plug_kwh_kwc, year.specific_yield_main_kwh_kwc],
      color: c.solar,
    }],
    { unit: "kwh-precise", bottomPadding: 58, legendBottomOffset: 14, maxValuePadding: 1.15 },
  );
}

function drawAnnualChart() {
  const c = colors();
  const selectedIndex = data.years.findIndex((year) => year.year === state.selectedYear);
  drawBarChart(
    el("annualChart"),
    data.years.map((year) => String(year.year)),
    [
      { label: "Production", values: data.years.map((year) => year.production_kwh), color: c.solar },
      { label: "Conso réseau", values: data.years.map((year) => year.consumption_kwh), color: c.accent2 },
    ],
    { shortLabels: false, highlightIndex: selectedIndex },
  );
}

function drawMonthlyConsumptionComparisonChart() {
  const c = colors();
  const fallbackPalette = [c.accent, c.accent2, c.accent3, c.good, c.solar, "#7B61FF", "#FF9F1C", "#6B7280"];
  const rows = monthlyConsumptionRows();
  const labels = monthLabels();
  const series = rows.map((row, index) => ({
    label: String(row.year),
    values: labels.map((_, monthIndex) => {
      const month = row.months[monthIndex];
      return hasMonthData(month) ? month.consumption_kwh : 0;
    }),
    color: c.years[row.year] || fallbackPalette[index % fallbackPalette.length],
  }));

  drawBarChart(el("monthlyConsumptionChart"), labels, series, {
    unit: "kwh",
    bottomPadding: 76,
    legendBottomOffset: 18,
    topPadding: 6,
    maxValuePadding: 1.04,
    highlightSeriesLabels: [String(state.highlightedYear)],
  });
}

function drawClimateChart() {
  const canvas = el("climateChart");
  if (!canvas) return;
  const year = weatherYearByValue(state.selectedYear) || latestWeatherYear();
  if (!weatherData || !year || !Array.isArray(year.months)) {
    const { ctx, width, height } = setupCanvas(canvas);
    const c = colors();
    ctx.fillStyle = c.muted;
    ctx.font = "13px Segoe UI, Arial, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("Données météo non générées", width / 2, height / 2);
    return;
  }

  const c = colors();
  const labels = year.months.map((month) => month.label || DEFAULT_MONTH_LABELS[(month.month || 1) - 1]);
  drawBarChart(
    canvas,
    labels,
    [
      { label: "≥ 30 °C", values: year.months.map((month) => month.hot_days_30 || 0), color: c.climateHeat },
      { label: "Gel", values: year.months.map((month) => month.frost_days || 0), color: c.climateCold },
      { label: "Pluie", values: year.months.map((month) => month.rain_days_1mm || 0), color: c.climateRain },
      { label: "≥ 20 mm", values: year.months.map((month) => month.heavy_rain_days_20mm || 0), color: c.climateStorm },
    ],
    {
      unit: "days",
      bottomPadding: 78,
      legendBottomOffset: 18,
      maxValuePadding: 1.22,
    },
  );
}

function drawMonthlyChart() {
  const c = colors();
  const months = monthsForYear(state.selectedYear);
  const labels = months.map((month) => month.label);
  let series;
  let unit = "kwh";

  if (state.metric === "money") {
    unit = "eur";
    series = [
      { label: "Coût", values: months.map((month) => month.total_eur), color: c.accent3 },
      { label: "Économie théorique", values: months.map((month) => month.theoretical_savings_eur), color: c.solar },
    ];
  } else if (state.metric === "solar") {
    const year = yearByValue(state.selectedYear);
    const injectionByMonth = distributeAnnualInjection(year, months);
    series = [
      { label: "Autoconsommée (estim.)", values: months.map((month, index) => Math.max(month.production_kwh - injectionByMonth[index], 0)), color: c.solar },
      { label: "Injectée (estim.)", values: injectionByMonth, color: c.warn },
    ];
  } else {
    series = [
      { label: "Production", values: months.map((month) => month.production_kwh), color: c.solar },
      { label: "Consommation", values: months.map((month) => month.consumption_kwh), color: c.accent2 },
    ];
  }

  drawBarChart(el("monthlyChart"), labels, series, { unit });
}

function distributeAnnualInjection(year, months) {
  const totalProduction = months.reduce((sum, month) => sum + month.production_kwh, 0);
  if (!totalProduction || !year.injection_kwh) return months.map(() => 0);
  return months.map((month) => (month.production_kwh / totalProduction) * year.injection_kwh);
}

function drawDailyChart() {
  const c = colors();
  let rows = dailyForYear(state.selectedYear);
  if (state.dailyMode === "recent") {
    rows = rows.slice(-45);
  }
  const labels = rows.map((row) => {
    const date = new Date(`${row.date}T00:00:00`);
    return `${String(date.getDate()).padStart(2, "0")}/${String(date.getMonth() + 1).padStart(2, "0")}`;
  });
  drawLineChart(
    el("dailyChart"),
    labels,
    [
      { label: "Production", values: rows.map((row) => row.production_kwh), color: c.solar },
      { label: "Conso réseau", values: rows.map((row) => row.consumption_kwh), color: c.accent2 },
    ],
  );
}

function bindTooltip(canvas, regions, template, nearestPoint = false) {
  const tooltip = el("chartTooltip");
  canvas.onmouseleave = () => {
    tooltip.style.display = "none";
  };
  canvas.onmousemove = (event) => {
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    let hit = null;

    if (nearestPoint) {
      let bestDistance = Infinity;
      regions.forEach((item) => {
        const distance = Math.abs(item.x - x) + Math.abs(item.y - y) * 0.25;
        if (distance < bestDistance && distance < 28) {
          bestDistance = distance;
          hit = item;
        }
      });
    } else {
      hit = regions.find(
        (item) =>
          x >= item.x &&
          x <= item.x + item.width &&
          y >= Math.min(item.y, item.y + item.height) &&
          y <= Math.max(item.y, item.y + item.height),
      );
    }

    if (!hit) {
      tooltip.style.display = "none";
      return;
    }

    tooltip.innerHTML = template(hit);
    tooltip.style.display = "block";
    tooltip.style.left = `${event.clientX + 14}px`;
    tooltip.style.top = `${event.clientY + 14}px`;
  };
}

function renderCharts() {
  drawClimateChart();
  drawMonthlyChart();
  drawPaybackChart();
  drawPhasePerformanceChart();
  drawAnnualChart();
  drawMonthlyConsumptionComparisonChart();
  drawDailyChart();
}

function render() {
  renderControls();
  renderInsights();
  renderQualityStrip();
  renderStrategy();
  renderClimate();
  renderFocus();
  renderTable();
  renderMonthlyConsumptionTable();
  renderProjection();
  renderCharts();
}

const PAGE_META = {
  cockpit: ["Vue essentielle", "Cockpit solaire"],
  amortissement: ["Projection financière", "Amortissement"],
  production: ["Énergie solaire", "Production"],
  linky: ["Compteur réseau", "Linky"],
  apsystems: ["Production directe", "APsystems"],
  meteo: ["Contexte climatique", "Météo-France"],
  controles: ["Audit et méthode", "Contrôles"],
};

function activePageFromHash() {
  const route = location.hash.replace(/^#\/?/, "").split("/")[0];
  return PAGE_META[route] ? route : "cockpit";
}

function showPage() {
  const route = activePageFromHash();
  document.querySelectorAll("[data-page]").forEach((page) => { page.hidden = page.dataset.page !== route; });
  document.querySelectorAll("[data-route]").forEach((link) => {
    const active = link.dataset.route === route;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  });
  el("pageEyebrow").textContent = PAGE_META[route][0];
  el("pageTitle").childNodes[0].nodeValue = `${PAGE_META[route][1]} `;
  document.title = `${PAGE_META[route][1]} — Cockpit solaire V3`;
  window.scrollTo({ top: 0, behavior: "auto" });
  requestAnimationFrame(() => {
    renderCharts();
    if (route === "apsystems") drawAPsystemsDailyChart(apsystemsKnown);
  });
}

function setupNavigation() {
  window.addEventListener("hashchange", showPage);
  showPage();
}

setupTheme();
setupLinky();
renderStaticInfo();
renderKpis();
render();
setupNavigation();

// Independent APsystems panel; never mutates the Excel model or global calculations.
function compareAPsystems(excelRows, apiRows, devices) {
  const results = [];
  const excel = new Map(excelRows.map(r => [r.date, r]));
  for (const installation of ["PLUG", "MAIN"]) {
    const expected = devices.filter(d => d.installation === installation);
    if (!expected.length || expected.some(d => d.timezone !== "Europe/Paris")) continue;
    const dates = [...new Set(apiRows.map(r => r.date))].sort();
    const common = [];
    for (const day of dates) {
      const value = excel.get(day)?.[installation === "MAIN" ? "production_main_kwh" : "production_plug_kwh"];
      if (value == null || !Number.isFinite(Number(value))) continue;
      const rows = expected.map(d => apiRows.find(r => r.date === day && r.eid === d.eid && r.complete === 1 && r.kwh != null));
      if (rows.some(r => !r)) continue;
      common.push({date: day, excel: Number(value), api: rows.reduce((s,r) => s + r.kwh, 0)});
    }
    if (!common.length) continue;
    const excelKwh = common.reduce((s,r) => s+r.excel,0);
    const apiKwh = common.reduce((s,r) => s+r.api,0);
    const deltaKwh = apiKwh-excelKwh;
    const percent = excelKwh === 0 ? null : deltaKwh/excelKwh*100;
    results.push({installation, days:common.length, start:common[0].date, end:common.at(-1).date,
      excelKwh, apiKwh, deltaKwh, percent,
      warning:Math.abs(deltaKwh)>0.1 && (percent == null || Math.abs(percent)>2)});
  }
  return results;
}

let apsystemsKnown = window.APSYSTEMS_DATA || {configured:false,status:"not_configured"};

function drawAPsystemsDailyChart(payload) {
  const canvas = el("apsystemsDailyChart");
  if (!canvas) return;
  const rows = (payload?.daily || []).filter((row) => row.kwh != null).slice(-21);
  if (!rows.length) {
    const { ctx, width, height } = setupCanvas(canvas);
    ctx.fillStyle = colors().muted; ctx.textAlign = "center"; ctx.font = "13px Segoe UI, Arial, sans-serif";
    ctx.fillText("Aucune mesure quotidienne disponible", width / 2, height / 2);
    return;
  }
  drawBarChart(canvas, rows.map((row) => new Intl.DateTimeFormat("fr-FR", {day:"2-digit", month:"short"}).format(new Date(`${row.date}T00:00:00`))), [{label:"Production APsystems", values:rows.map((row) => Number(row.kwh)), color:colors().solar}], {unit:"kwh-precise", bottomPadding:70, legendBottomOffset:18});
}

function renderAPsystemsDetails(payload) {
  const rows = Array.isArray(payload?.daily) ? payload.daily : [];
  const table = el("apsystemsDailyTable");
  if (!table) return;
  const complete = rows.filter((row) => row.complete === 1);
  const total = complete.reduce((sum, row) => sum + Number(row.kwh || 0), 0);
  el("apsystemsRowsStatus").textContent = rows.length ? `${formatNumber(rows.length)} jours` : "Aucune mesure";
  el("apsystemsDetailSummary").innerHTML = `<div><span>Mois en cours</span><strong>${formatKwh(payload?.summary?.month || 0, 2)}</strong></div><div><span>Année</span><strong>${formatKwh(payload?.summary?.year || 0, 2)}</strong></div><div><span>Jours clos affichés</span><strong>${formatKwh(total, 2)}</strong></div>`;
  table.innerHTML = rows.length ? rows.slice(-31).reverse().map((row) => `<tr><td>${formatLinkyDate(row.date)}</td><td>${row.installation || row.eid || "--"}</td><td>${formatKwh(row.kwh, 2)}</td><td><span class="row-state ${row.complete === 1 ? "complete" : "live"}">${row.complete === 1 ? "Clos" : "En cours"}</span></td></tr>`).join("") : `<tr><td colspan="4">Aucune mesure quotidienne disponible.</td></tr>`;
  drawAPsystemsDailyChart(payload);
}

function renderAPsystems(payload, available) {
  apsystemsKnown = payload;
  const labels = {ok:"Connecté", not_configured:"Non configuré", never_synced:"À synchroniser",
    authentication_error:"Authentification refusée", offline:"Hors ligne", quota_warning:"Quota à surveiller",
    no_data:"Aucune donnée", api_error:"Erreur API", timestamp_confirmation_required:"Configuration à confirmer",
    sync_in_progress:"Synchronisation en cours"};
  const status = available ? payload.status : "offline";
  el("apsystemsStatus").dataset.status = status;
  el("apsystemsStatus").querySelector("span").textContent = labels[status] || "À vérifier";
  const recent = payload.summary?.fetched_at && new Date(payload.summary.fetched_at).toLocaleDateString("fr-FR",{timeZone:"Europe/Paris"}) === new Date().toLocaleDateString("fr-FR",{timeZone:"Europe/Paris"});
  el("apsystemsToday").textContent = recent && payload.summary.today != null ? `${formatNumber(payload.summary.today,2)} kWh` : "--";
  const age = Date.now()-Date.parse(payload.last_power_at);
  el("apsystemsPower").textContent = available && age >= 0 && age <= 1200000 && payload.current_power_w != null ? `${formatNumber(payload.current_power_w,0)} W` : "--";
  el("apsystemsLastSync").textContent = formatLinkyDate(payload.last_sync,true);
  el("apsystemsLastData").textContent = formatLinkyDate(payload.last_data,true);
  el("apsystemsQuota").textContent = `${payload.calls_month || 0} / 1 000`;
  el("apsystemsSyncButton").disabled = !available || !payload.configured || status === "timestamp_confirmation_required";
  const communication = {1:"Système normal",2:"Alarme ou enregistrement à contrôler",3:"Problème de communication ECU",4:"Aucune remontée ECU"};
  el("apsystemsDevices").textContent = (payload.devices?.length ? payload.devices.map(d => `ECU ${d.eid} → ${d.installation || "association MAIN / PLUG à renseigner dans config.local.json"}`).join(" ; ") : "Aucun équipement détecté.") + (payload.communication ? ` — ${communication[payload.communication.light] || "État inconnu"} (contrôlé le ${payload.communication.checked_day}).` : "");
  const comparisons = compareAPsystems(data.daily, payload.daily || [], payload.devices || []);
  el("apsystemsComparison").textContent = comparisons.length ? comparisons.map(c => `${c.installation} : ${c.days} journées communes, ${c.start} → ${c.end}. Excel ${formatNumber(c.excelKwh,2)} kWh / API ${formatNumber(c.apiKwh,2)} kWh. Écart ${formatNumber(c.deltaKwh,2)} kWh (${c.percent == null ? "% non calculable" : formatNumber(c.percent,2)+" %"}). ${c.warning ? "Écart à contrôler" : "Dans le seuil de contrôle"}.`).join(" ") : "Aucune journée commune comparable. Mapping et journées closes requis.";
  el("apsystemsMessage").textContent = !available ? "Service local indisponible. Dernières données connues conservées." : status === "not_configured" ? "Configuration privée dans config.local.json, puis redémarrage du cockpit." : status === "timestamp_confirmation_required" ? "Confirmer l’unité du timestamp APsystems avant le premier appel réel (voir README)." : status === "ok" ? "Données API conservées séparément d’Excel." : "Dernières données connues conservées ; consulter le statut avant de réessayer.";
  if (available && payload.last_error?.response_code === 2004) {
    el("apsystemsMessage").textContent = "APsystems refuse l’accès (code 2004). Vérifier le SID et les droits OpenAPI du compte. Dernières données conservées.";
  }
  renderAPsystemsDetails(payload);
}

async function refreshAPsystems() {
  try {
    const response = await fetch("/api/apsystems/status", {cache:"no-store"});
    if (!response.ok) throw new Error("unavailable");
    renderAPsystems(await response.json(),true);
  } catch (_) { renderAPsystems(apsystemsKnown,false); }
}
el("apsystemsSyncButton").addEventListener("click", async () => {
  el("apsystemsSyncButton").disabled = true;
  el("apsystemsMessage").textContent = "Synchronisation APsystems en cours…";
  try {
    const response = await fetch("/api/apsystems/sync", {method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});
    if (!response.ok) throw new Error("unavailable");
    const result = await response.json();
    renderAPsystems(result.dashboard || apsystemsKnown,true);
  } catch (_) { renderAPsystems(apsystemsKnown,false); }
});
refreshAPsystems();

let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(renderCharts, 120);
});
