const $ = (id) => document.getElementById(id);

async function json(response) {
  const text = await response.text();
  try { return text ? JSON.parse(text) : {}; }
  catch { return {message: text}; }
}

function lines(value) {
  return String(value || "").split(/\n+/).map(item => item.trim()).filter(Boolean);
}

function slug(value) {
  return String(value || "")
    .toLowerCase().trim().replace(/_/g, "-")
    .replace(/[^a-z0-9-]+/g, "-").replace(/-+/g, "-").replace(/^-|-$/g, "")
    .slice(0, 80);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
}

function field(card, name) {
  return card.querySelector(`[data-field="${name}"]`);
}

function cardId(card) {
  return slug(field(card, "id")?.value || card.dataset.category);
}

function cardLabel(card) {
  return (field(card, "label")?.value || cardId(card).replace(/-/g, " ")).trim();
}

function categoryCards() {
  return Array.from(document.querySelectorAll("#category-list .category-card[data-category]"));
}

function setStatus(message, error=false) {
  const target = $("classification-status");
  target.textContent = message;
  target.style.color = error ? "#ffb4aa" : "#d2dfdc";
}

function markChanged() {
  setStatus("Unsaved changes");
}

function refreshCard(card) {
  const id = cardId(card) || "new-category";
  const label = cardLabel(card) || "New category";
  const enabled = card.dataset.protected === "true" ? true : Boolean(field(card, "enabled")?.checked);
  const profile = field(card, "search_profile")?.value || "general-product";
  const minSources = Number(field(card, "min_priced_sources")?.value || 1);
  const key = card.querySelector(".category-key");
  const display = card.querySelector("[data-display-label]");
  const summaryProfile = card.querySelector("[data-summary-profile]");
  const summaryPrice = card.querySelector("[data-summary-price]");
  if (key) key.textContent = id;
  if (display) display.textContent = label;
  if (summaryProfile) summaryProfile.textContent = profile;
  if (summaryPrice) summaryPrice.textContent = `${minSources} priced source${minSources === 1 ? "" : "s"}`;
  card.classList.toggle("disabled-category", !enabled);
  let disabledPill = card.querySelector(".disabled-pill");
  if (!enabled && !disabledPill) {
    disabledPill = document.createElement("span");
    disabledPill.className = "disabled-pill";
    disabledPill.textContent = "Disabled";
    card.querySelector(".category-title")?.appendChild(disabledPill);
  } else if (enabled && disabledPill) {
    disabledPill.remove();
  }
}

function rebuildIndex() {
  const target = $("category-index");
  target.innerHTML = "";
  categoryCards().forEach(card => {
    refreshCard(card);
    const id = cardId(card) || "new-category";
    const label = cardLabel(card) || "New category";
    const enabled = card.dataset.protected === "true" ? true : Boolean(field(card, "enabled")?.checked);
    const minSources = Number(field(card, "min_priced_sources")?.value || 1);
    const link = document.createElement("a");
    link.href = `#${card.id}`;
    link.dataset.indexCategory = id;
    link.innerHTML = `<strong>${escapeHtml(label)}</strong><span>${escapeHtml(id)}</span><em>${enabled ? "" : "Disabled · "}${minSources} priced source${minSources === 1 ? "" : "s"}</em>`;
    target.appendChild(link);
  });
}

function collectRules() {
  const categories = {};
  const ids = new Set();
  let error = "";

  categoryCards().forEach((card, index) => {
    const id = cardId(card);
    if (!id) {
      error ||= "Every category needs a valid category ID.";
      return;
    }
    if (ids.has(id)) {
      error ||= `Category ID '${id}' is duplicated.`;
      return;
    }
    ids.add(id);
    const get = (name) => field(card, name);
    const protectedCategory = card.dataset.protected === "true";
    categories[id] = {
      id,
      label: cardLabel(card) || id,
      enabled: protectedCategory ? true : Boolean(get("enabled")?.checked),
      order: protectedCategory ? 1000 : (index + 1) * 10,
      search_profile: protectedCategory ? "general-product" : (get("search_profile")?.value || "general-product"),
      keywords: get("keywords") ? lines(get("keywords").value) : [],
      phrases: get("phrases") ? lines(get("phrases").value) : [],
      patterns: get("patterns") ? lines(get("patterns").value) : [],
      min_priced_sources: Number(get("min_priced_sources")?.value || 1),
      require_independent_domains: Boolean(get("require_independent_domains")?.checked),
      strategy: get("strategy")?.value || "",
      evidence_notes: get("evidence_notes")?.value || "",
      stopping_notes: get("stopping_notes")?.value || "",
      fallback_notes: get("fallback_notes")?.value || "",
      future_notes: get("future_notes")?.value || "",
    };
  });

  if (!categories["general-product"]) error ||= "The protected general-product catch-all category is required.";
  if (error) throw new Error(error);
  return {version: 2, categories};
}

async function saveRules() {
  let payload;
  try { payload = collectRules(); }
  catch (error) { setStatus(error.message, true); return; }

  setStatus("Saving rules…");
  const response = await fetch("/api/classifications", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
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
    target.innerHTML = `<strong>Could not classify</strong><p>${escapeHtml(data.message || "Unknown error")}</p>`;
    return;
  }
  const result = data.result;
  target.innerHTML = `
    <span class="eyebrow">Selected category</span>
    <strong>${escapeHtml(result.label)} <code>${escapeHtml(result.category)}</code></strong>
    <p>${escapeHtml(result.reason)}</p>
    <div class="result-meta">
      <span>Priority ${escapeHtml(result.priority)}</span>
      <span>Profile: ${escapeHtml(result.search_profile)}</span>
      <span>${result.min_priced_sources} priced sources required</span>
      <span>${result.require_independent_domains ? "Independent domains required" : "Duplicate domains allowed"}</span>
    </div>
    <p style="margin-top:10px"><b>Search strategy:</b> ${escapeHtml(result.strategy)}</p>`;
}

async function resetRules() {
  if (!window.confirm("Reset all categories, classification and stopping rules to the application defaults? Custom categories will be removed.")) return;
  const response = await fetch("/api/classifications/reset", {method: "POST"});
  const data = await json(response);
  if (!response.ok || !data.ok) {
    setStatus(data.message || "Could not reset rules.", true);
    return;
  }
  window.location.reload();
}

function uniqueId(base="new-category") {
  const existing = new Set(categoryCards().map(card => cardId(card)));
  let candidate = slug(base) || "new-category";
  let counter = 2;
  while (existing.has(candidate)) candidate = `${slug(base) || "new-category"}-${counter++}`;
  return candidate;
}

function cloneStructure() {
  const source = categoryCards().find(card => card.dataset.protected !== "true");
  if (!source) throw new Error("No category template is available.");
  const card = source.cloneNode(true);
  card.open = true;
  card.dataset.protected = "false";
  card.querySelector(".disabled-pill")?.remove();
  card.querySelector(".catchall-note")?.remove();
  if (!card.querySelector(".delete-category")) {
    const toolbar = card.querySelector(".category-toolbar");
    const button = document.createElement("button");
    button.className = "btn danger small delete-category";
    button.type = "button";
    button.textContent = "Delete";
    toolbar?.appendChild(button);
  }
  const idField = field(card, "id");
  const profile = field(card, "search_profile");
  if (idField) idField.readOnly = false;
  if (profile) profile.disabled = false;
  return card;
}

function populateCard(card, values={}) {
  const put = (name, value) => {
    const control = field(card, name);
    if (!control) return;
    if (control.type === "checkbox") control.checked = Boolean(value);
    else control.value = value ?? "";
  };
  Object.entries(values).forEach(([name, value]) => {
    if (["keywords", "phrases", "patterns"].includes(name) && Array.isArray(value)) put(name, value.join("\n"));
    else put(name, value);
  });
  const id = uniqueId(values.id || values.label || "new-category");
  put("id", id);
  card.dataset.category = id;
  card.id = `category-${id}`;
  refreshCard(card);
}

function addCategory(sourceCard=null) {
  let card;
  try { card = cloneStructure(); }
  catch (error) { setStatus(error.message, true); return; }

  const values = sourceCard ? {
    id: `${cardId(sourceCard)}-copy`,
    label: `${cardLabel(sourceCard)} copy`,
    enabled: true,
    search_profile: field(sourceCard, "search_profile")?.value || "general-product",
    keywords: field(sourceCard, "keywords") ? lines(field(sourceCard, "keywords").value) : [],
    phrases: field(sourceCard, "phrases") ? lines(field(sourceCard, "phrases").value) : [],
    patterns: field(sourceCard, "patterns") ? lines(field(sourceCard, "patterns").value) : [],
    min_priced_sources: Number(field(sourceCard, "min_priced_sources")?.value || 3),
    require_independent_domains: Boolean(field(sourceCard, "require_independent_domains")?.checked),
    strategy: field(sourceCard, "strategy")?.value || "",
    evidence_notes: field(sourceCard, "evidence_notes")?.value || "",
    stopping_notes: field(sourceCard, "stopping_notes")?.value || "",
    fallback_notes: field(sourceCard, "fallback_notes")?.value || "",
    future_notes: field(sourceCard, "future_notes")?.value || "",
  } : {
    id: "new-category",
    label: "New category",
    enabled: true,
    search_profile: "general-product",
    keywords: [], phrases: [], patterns: [],
    min_priced_sources: 3,
    require_independent_domains: true,
    strategy: "Prioritise exact-description supplier, distributor and catalogue prices before broader comparable-product evidence.",
    evidence_notes: "Define which price-bearing evidence should count for this category.",
    stopping_notes: "Continue until the configured commercial-evidence threshold is met or research limits are exhausted.",
    fallback_notes: "Use model knowledge only after web research is exhausted, and label it separately.",
    future_notes: "Add category-specific rules here as the category matures.",
  };

  populateCard(card, values);
  const fallback = categoryCards().find(item => item.dataset.protected === "true");
  if (fallback) fallback.before(card); else $("category-list").appendChild(card);
  rebuildIndex();
  markChanged();
  field(card, "label")?.focus();
  card.scrollIntoView({behavior: "smooth", block: "start"});
}

function deleteCategory(card) {
  if (card.dataset.protected === "true") {
    setStatus("The general-product catch-all category cannot be deleted.", true);
    return;
  }
  if (!window.confirm(`Delete '${cardLabel(card)}'? The category will be removed when you save.`)) return;
  card.remove();
  rebuildIndex();
  markChanged();
}

function moveCategory(card, direction) {
  if (card.dataset.protected === "true") return;
  const movable = categoryCards().filter(item => item.dataset.protected !== "true");
  const index = movable.indexOf(card);
  const targetIndex = index + direction;
  if (targetIndex < 0 || targetIndex >= movable.length) return;
  const target = movable[targetIndex];
  if (direction < 0) target.before(card); else target.after(card);
  const fallback = categoryCards().find(item => item.dataset.protected === "true");
  if (fallback) $("category-list").appendChild(fallback);
  rebuildIndex();
  markChanged();
}

$("save-rules").addEventListener("click", saveRules);
$("save-rules-bottom").addEventListener("click", saveRules);
$("test-classification").addEventListener("click", testClassification);
$("classification-query").addEventListener("keydown", event => {
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") testClassification();
});
$("reset-rules").addEventListener("click", resetRules);
$("add-category").addEventListener("click", () => addCategory());
$("add-category-bottom").addEventListener("click", () => addCategory());

$("category-list").addEventListener("click", event => {
  const card = event.target.closest(".category-card");
  if (!card) return;
  if (event.target.closest(".duplicate-category")) addCategory(card);
  else if (event.target.closest(".delete-category")) deleteCategory(card);
  else if (event.target.closest(".move-up")) moveCategory(card, -1);
  else if (event.target.closest(".move-down")) moveCategory(card, 1);
});

$("category-list").addEventListener("input", event => {
  const card = event.target.closest(".category-card");
  if (card) { refreshCard(card); rebuildIndex(); markChanged(); }
});
$("category-list").addEventListener("change", event => {
  const card = event.target.closest(".category-card");
  if (card) { refreshCard(card); rebuildIndex(); markChanged(); }
});

rebuildIndex();
