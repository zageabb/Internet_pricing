const $ = (id) => document.getElementById(id);

async function json(response) {
  const text = await response.text();
  try { return text ? JSON.parse(text) : {}; }
  catch { return {message: text}; }
}

function lines(value) {
  return String(value || "").split(/\n+/).map(item => item.trim()).filter(Boolean);
}

function collectRules() {
  const categories = {};
  document.querySelectorAll(".category-card[data-category]").forEach(card => {
    const category = card.dataset.category;
    const get = (field) => card.querySelector(`[data-field="${field}"]`);
    const keywords = get("keywords");
    const phrases = get("phrases");
    const patterns = get("patterns");
    categories[category] = {
      keywords: keywords ? lines(keywords.value) : [],
      phrases: phrases ? lines(phrases.value) : [],
      patterns: patterns ? lines(patterns.value) : [],
      min_priced_sources: Number(get("min_priced_sources")?.value || 1),
      require_independent_domains: Boolean(get("require_independent_domains")?.checked),
      strategy: get("strategy")?.value || "",
      evidence_notes: get("evidence_notes")?.value || "",
      stopping_notes: get("stopping_notes")?.value || "",
      fallback_notes: get("fallback_notes")?.value || "",
      future_notes: get("future_notes")?.value || "",
    };
  });
  return {version: 1, categories};
}

function setStatus(message, error=false) {
  const target = $("classification-status");
  target.textContent = message;
  target.style.color = error ? "#ffb4aa" : "#d2dfdc";
}

async function saveRules() {
  setStatus("Saving rules…");
  const response = await fetch("/api/classifications", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(collectRules()),
  });
  const data = await json(response);
  if (!response.ok || !data.ok) {
    setStatus(data.message || "Could not save classification rules.", true);
    return;
  }
  setStatus("Rules saved. New searches will use them immediately.");
  window.setTimeout(() => window.location.reload(), 450);
}

async function testClassification() {
  const query = $("classification-query").value.trim();
  const target = $("classification-result");
  if (!query) {
    target.classList.remove("hidden");
    target.innerHTML = "<strong>Enter a request first.</strong>";
    return;
  }
  target.classList.remove("hidden");
  target.innerHTML = "<strong>Classifying…</strong>";
  const response = await fetch("/api/classifications/test", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({query}),
  });
  const data = await json(response);
  if (!response.ok || !data.ok) {
    target.innerHTML = `<strong>Could not classify</strong><p>${data.message || "Unknown error"}</p>`;
    return;
  }
  const result = data.result;
  target.innerHTML = `
    <span class="eyebrow">Selected category</span>
    <strong>${result.label} <code>${result.category}</code></strong>
    <p>${result.reason}</p>
    <div class="result-meta">
      <span>Priority ${result.priority}</span>
      <span>${result.min_priced_sources} priced sources required</span>
      <span>${result.require_independent_domains ? "Independent domains required" : "Duplicate domains allowed"}</span>
    </div>
    <p style="margin-top:10px"><b>Search strategy:</b> ${result.strategy}</p>`;
}

async function resetRules() {
  if (!window.confirm("Reset all classification and stopping rules to the application defaults?")) return;
  const response = await fetch("/api/classifications/reset", {method: "POST"});
  const data = await json(response);
  if (!response.ok || !data.ok) {
    setStatus(data.message || "Could not reset rules.", true);
    return;
  }
  window.location.reload();
}

$("save-rules").addEventListener("click", saveRules);
$("save-rules-bottom").addEventListener("click", saveRules);
$("test-classification").addEventListener("click", testClassification);
$("classification-query").addEventListener("keydown", event => {
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") testClassification();
});
$("reset-rules").addEventListener("click", resetRules);

document.querySelectorAll("#classification-form textarea, #classification-form input").forEach(control => {
  control.addEventListener("input", () => setStatus("Unsaved changes"));
  control.addEventListener("change", () => setStatus("Unsaved changes"));
});
