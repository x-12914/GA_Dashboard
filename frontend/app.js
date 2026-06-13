const $ = (sel) => document.querySelector(sel);

const KEY_METRICS = [
  ["totalRevenue", "Revenue", (v) => "$" + Math.round(v).toLocaleString()],
  ["conversions", "Conversions", (v) => Math.round(v).toLocaleString()],
  ["sessions", "Sessions", (v) => Math.round(v).toLocaleString()],
  ["totalUsers", "Users", (v) => Math.round(v).toLocaleString()],
  ["engagementRate", "Engagement", (v) => (v * 100).toFixed(1) + "%"],
];

async function loadStatus() {
  try {
    const s = await (await fetch("/api/status")).json();
    $("#statusbar").innerHTML =
      `<span class="pill">Data: ${s.mode}</span>` +
      `<span class="pill">Analyzer: ${s.analyzer}</span>` +
      (s.mode === "mock" ? `<span class="pill">⚠ using sample data — connect GA4 in .env</span>` : "");
  } catch (_) {}
}

function metricCard([key, label, fmt], totals) {
  const m = totals[key];
  if (!m) return "";
  const up = m.change_pct >= 0;
  const cls = up ? "up" : "down";
  const arrow = up ? "▲" : "▼";
  return `<div class="metric">
    <div class="label">${label}</div>
    <div class="value">${fmt(m.value)}</div>
    <div class="delta ${cls}">${arrow} ${Math.abs(m.change_pct)}%</div>
  </div>`;
}

function suggestionCard(s) {
  const p = (s.priority || "low").toLowerCase();
  return `<div class="suggestion ${p}">
    <div class="head">
      <h4>${s.title}</h4>
      <div>
        <span class="tag ${p}">${p}</span>
        <span class="tag">${s.category || ""}</span>
      </div>
    </div>
    <div class="row"><b>The problem</b>${s.problem}</div>
    <div class="row"><b>Do this</b>${s.action}</div>
    ${s.expected_impact ? `<div class="impact">💰 ${s.expected_impact}</div>` : ""}
  </div>`;
}

async function analyze() {
  const days = $("#days").value;
  const btn = $("#refresh");
  btn.disabled = true;
  btn.textContent = "Analyzing…";
  $("#suggestions").innerHTML = `<div class="loading">Reading your analytics and thinking…</div>`;
  $("#metrics").innerHTML = "";
  $("#summary").classList.add("hidden");

  try {
    const data = await (await fetch(`/api/insights?days=${days}`)).json();
    const { report, advice } = data;

    $("#summary").innerHTML = `<h3>Health check</h3>${advice.summary}`;
    $("#summary").classList.remove("hidden");

    $("#metrics").innerHTML = KEY_METRICS.map((m) => metricCard(m, report.totals)).join("");

    $("#suggestions").innerHTML = (advice.suggestions || []).length
      ? advice.suggestions.map(suggestionCard).join("")
      : `<div class="loading">No major issues found 🎉</div>`;

    $("#raw").textContent = JSON.stringify(report, null, 2);
    $("#engine").textContent = `Analyzer: ${advice.engine} · Data source: ${report.source}`;
  } catch (e) {
    $("#suggestions").innerHTML = `<div class="loading">Error: ${e}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Analyze";
  }
}

// ---- Store auditor -------------------------------------------------------
function checkRow(c) {
  return `<div class="check">
    <span class="dot ${c.status}"></span>
    <div>
      <div class="name">${c.name}</div>
      <div class="detail">${c.detail}</div>
      ${c.fix ? `<div class="fix">→ ${c.fix}</div>` : ""}
    </div>
  </div>`;
}

async function auditStore() {
  const url = $("#store-url").value.trim();
  if (!url) return;
  const wantEmail = $("#gen-email").checked;
  const btn = $("#audit-btn");
  const out = $("#audit-result");
  btn.disabled = true;
  btn.textContent = "Auditing…";
  out.innerHTML = `<div class="loading">Fetching and analyzing the store…</div>`;

  try {
    const r = await (await fetch(`/api/audit?url=${encodeURIComponent(url)}&email=${wantEmail}`)).json();
    if (!r.ok) {
      out.innerHTML = `<div class="loading">${r.error || "Could not audit that URL."}</div>`;
      return;
    }
    let html = `<div class="audit-score">Store health: <b>${r.score}</b>/100`;
    if (!r.is_shopify) html += ` <span class="pill">not detected as Shopify</span>`;
    html += `</div>`;
    html += `<div id="audit-checks">` + r.checks.map(checkRow).join("");
    // Placeholder for the slow PageSpeed check — filled in (or removed) below.
    html += `<div class="check" id="speed-row">
      <span class="dot warn"></span>
      <div><div class="name">Mobile speed (Google PageSpeed)</div>
      <div class="detail">checking… (can take ~30s for heavy stores)</div></div>
    </div></div>`;

    if (r.cold_email) {
      html += `<div class="email-draft">
        <h3>Cold email draft (${r.cold_email.engine})</h3>
        <textarea id="email-text">${r.cold_email.email}</textarea>
        <button class="copy-btn" id="copy-email">Copy email</button>
      </div>`;
    }
    out.innerHTML = html;

    // Lazily fetch the slow PageSpeed score and slot it in when ready.
    fetch(`/api/pagespeed?url=${encodeURIComponent(url)}`)
      .then((res) => res.json())
      .then((d) => {
        const row = document.getElementById("speed-row");
        if (!row) return;
        if (d.check) row.outerHTML = checkRow(d.check);
        else row.remove(); // site too heavy/slow for PSI, or no key
      })
      .catch(() => {
        const row = document.getElementById("speed-row");
        if (row) row.remove();
      });

    const copyBtn = $("#copy-email");
    if (copyBtn) {
      copyBtn.addEventListener("click", () => {
        navigator.clipboard.writeText($("#email-text").value);
        copyBtn.textContent = "Copied ✓";
        setTimeout(() => (copyBtn.textContent = "Copy email"), 1500);
      });
    }
  } catch (e) {
    out.innerHTML = `<div class="loading">Error: ${e}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Audit store";
  }
}

$("#audit-btn").addEventListener("click", auditStore);
$("#store-url").addEventListener("keydown", (e) => { if (e.key === "Enter") auditStore(); });

// ---- Prospect Finder -----------------------------------------------------
function healthClass(s) { return s >= 75 ? "health-good" : s >= 55 ? "health-mid" : "health-bad"; }

function prospectRow(p, i) {
  const hook = p.best_hook ? p.best_hook.name : "—";
  const email = p.email
    ? `<code>${p.email}</code> <button class="copy-mini" data-email="${p.email}">copy</button>`
    : `<span style="color:var(--high)">no email found</span>`;
  return `<div class="prospect-row" data-url="${p.url}">
    <div class="prospect-rank">${i + 1}</div>
    <div class="prospect-main">
      <div class="dom"><a href="https://${p.domain}" target="_blank" rel="noopener">${p.domain}</a>
        <span class="health-pill ${healthClass(p.score)}">health ${p.score}</span></div>
      <div class="prospect-meta">Top hook: <span class="hook">${hook}</span> · ${p.bad_count} issues</div>
      <div class="prospect-email">${email}</div>
    </div>
    <div class="prospect-actions">
      <button class="draft-one" data-url="${p.url}">Draft email</button>
    </div>
    <div class="prospect-emaildraft" style="grid-column:1/-1"></div>
  </div>`;
}

async function runProspect(body, btn) {
  const out = $("#prospect-result");
  const note = $("#prospect-note");
  btn.disabled = true;
  const label = btn.textContent;
  btn.textContent = "Working…";
  out.innerHTML = `<div class="loading">Discovering, auditing, and finding emails… (this can take ~30s)</div>`;
  note.textContent = "";
  try {
    const r = await (await fetch("/api/prospect", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    })).json();

    if (body.niche && !r.discovery_ready) {
      note.innerHTML = `⚠ Niche auto-discovery needs Google Custom Search set up. For now, paste store URLs in the box below instead.`;
    } else if (r.discovered_from) {
      note.textContent = `Discovered ${r.count} store(s) for “${r.discovered_from}”, ranked best-first.`;
    } else {
      note.textContent = `${r.count} store(s) audited and ranked best-first.`;
    }

    out.innerHTML = (r.prospects || []).length
      ? r.prospects.map(prospectRow).join("")
      : `<div class="loading">No Shopify prospects found. Try a different niche or paste URLs.</div>`;

    wireProspectButtons();
  } catch (e) {
    out.innerHTML = `<div class="loading">Error: ${e}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = label;
  }
}

function wireProspectButtons() {
  document.querySelectorAll(".copy-mini").forEach((b) =>
    b.addEventListener("click", () => {
      navigator.clipboard.writeText(b.dataset.email);
      b.textContent = "copied ✓";
      setTimeout(() => (b.textContent = "copy"), 1200);
    })
  );
  document.querySelectorAll(".draft-one").forEach((b) =>
    b.addEventListener("click", async () => {
      const row = b.closest(".prospect-row");
      const box = row.querySelector(".prospect-emaildraft");
      b.disabled = true; b.textContent = "Drafting…";
      try {
        const r = await (await fetch(`/api/audit?url=${encodeURIComponent(b.dataset.url)}&email=true`)).json();
        const email = r.cold_email ? r.cold_email.email : "(could not draft)";
        box.innerHTML = `<textarea>${email}</textarea>
          <button class="copy-draft">Copy email</button>`;
        box.querySelector(".copy-draft").addEventListener("click", () => {
          navigator.clipboard.writeText(box.querySelector("textarea").value);
          box.querySelector(".copy-draft").textContent = "Copied ✓";
        });
      } catch (e) {
        box.innerHTML = `<div class="loading">Error: ${e}</div>`;
      } finally {
        b.disabled = false; b.textContent = "Draft email";
      }
    })
  );
}

$("#find-btn").addEventListener("click", () => {
  const niche = $("#niche").value.trim();
  if (!niche) { $("#niche").focus(); return; }
  runProspect({ niche, want_email: true }, $("#find-btn"));
});
$("#niche").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#find-btn").click(); });
$("#audit-batch-btn").addEventListener("click", () => {
  const urls = $("#urls").value.split("\n").map((s) => s.trim()).filter(Boolean);
  if (!urls.length) { $("#urls").focus(); return; }
  runProspect({ urls, want_email: true }, $("#audit-batch-btn"));
});

$("#refresh").addEventListener("click", analyze);
loadStatus();
analyze();
