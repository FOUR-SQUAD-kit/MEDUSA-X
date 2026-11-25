// MEDUSA-X frontend (plain JS), served by the existing FastAPI app. No clinical data is invented here:
// everything shown comes from a backend response. All paths are in CONFIG; field-name guesses are in the
// normalize functions below and should be confirmed with Prajwal (backend).
//  POST /api/reconcile            multipart: files + patient_id -> timeline
//  GET  /api/timeline/{patient}   -> reconciled timeline
//  GET  /api/conflicts/{patient}  -> detected conflicts (optionally also missing/pending)
//  POST /api/verify-claims        {patient_id, claims:[text]} -> per-claim {status, evidence:[{doc,page,quote}]}
//  Optional (not yet agreed): GET /api/patients, POST /api/patients/{id}/escalations
//  Safety: POST /api/safety/evaluate-analysis and /evaluate-answer (safety_gate.py router)
const CONFIG = {
  base: "/api",
  paths: {
    patients: "/patients",
    reconcile: "/reconcile",
    timeline: id => `/timeline/${encodeURIComponent(id)}`,
    conflicts: id => `/conflicts/${encodeURIComponent(id)}`,
    verify: "/verify-claims",
    escalate: id => `/patients/${encodeURIComponent(id)}/escalations`,
    gateAnalysis: "/safety/evaluate-analysis",
    gateAnswer: "/safety/evaluate-answer"
  }
};
const $ = id => document.getElementById(id);
// Dev only: open index.html?mock=1 to read synthetic files from ./mock instead of the backend.
// In mock mode a statement containing "unsupported test" returns the insufficient-evidence example.
const MOCK = new URLSearchParams(location.search).has("mock");
function mockFile(path, opts) {
  if (path.startsWith("/patients") && !opts) return "patients.json";
  if (path.startsWith("/timeline") || path.startsWith("/reconcile")) return "timeline.json";
  if (path.startsWith("/conflicts")) return "conflicts.json";
  if (path.startsWith("/verify-claims")) return /unsupported test/i.test(opts && opts.body || "") ? "verify_insufficient.json" : "verify.json";
  return null;
}
let pid = null, uploaded = [];

function h(tag, attrs = {}, ...kids) {           // clinical text is inserted as text, never as HTML
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) k === "class" ? e.className = v : e.setAttribute(k, v);
  for (const c of kids.flat()) if (c != null && c !== false) e.append(c.nodeType ? c : document.createTextNode(c));
  return e;
}
const clear = (el, ...kids) => el.replaceChildren(...kids.flat().filter(Boolean));
const empty = t => h("p", { class: "empty" }, t);
const src = s => h("span", { class: "src" }, `${s.doc || "unknown document"}${s.page ? ", p." + s.page : ""}`);
const srcs = l => (l || []).map(src);

async function api(path, opts) {
  try {
    if (MOCK) {
      const f = mockFile(path, opts);
      if (!f) throw new Error("no mock");
      $("conn").hidden = false; $("conn").textContent = "Mock mode: synthetic test data, not real records";
      $("conn").style.cssText = "background:#fdf1dc;color:#a65f00";
      return await (await fetch("mock/" + f)).json();
    }
    const r = await fetch(CONFIG.base + path, opts);
    if (!r.ok) throw new Error("HTTP " + r.status);
    $("conn").hidden = true;
    return await r.json();
  } catch (e) {
    $("conn").hidden = false;
    $("conn").textContent = "Cannot reach the MEDUSA-X backend. No patient data is shown.";
    return null;
  }
}
const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

const FAIL_CLOSED = { decision: "escalate", reasons: [{ id: "gate_unavailable", text: "Safety check unavailable: treat everything below as unverified", severity: "high" }] };
async function gateFor(kind, payload) {
  if (payload.gate) return payload.gate;
  return (await post(kind === "answer" ? CONFIG.paths.gateAnswer : CONFIG.paths.gateAnalysis, payload)) || FAIL_CLOSED;
}

// ---- normalizers: tolerate a few likely field names; unknown shapes simply show as empty, never as made-up data
const arr = (r, ...keys) => Array.isArray(r) ? r : (keys.map(k => r && r[k]).find(Array.isArray) || []);
const srcOf = e => e.source || (e.document || e.doc ? { doc: e.document || e.doc, page: e.page } : null);
const normTimeline = r => arr(r, "timeline", "events").map(e => ({
  date: e.date || e.timestamp, event: e.event || e.description || e.text, status: e.status, source: srcOf(e) }));
function normConflicts(r) {
  const out = { conflicts: [], medications: [], missing: arr(r, "missing", "missing_information"), pending: arr(r, "pending", "pending_verification") };
  arr(r, "conflicts", "diagnosis_conflicts", "medication_discrepancies").forEach((c, i) => {
    const isMed = /med|drug/i.test(c.type || c.category || "") || c.drug;
    if (isMed) out.medications.push({ id: c.id ?? "m" + i, drug: c.drug || c.title || "Medication", issue: c.issue || c.description || "", severity: c.severity, sources: c.sources || (srcOf(c) ? [srcOf(c)] : []) });
    else out.conflicts.push({ id: c.id ?? "c" + i, title: c.title || c.description || c.diagnosis || "Conflict", severity: c.severity, claims: c.claims || [], sources: c.sources || [] });
  });
  return out;
}

async function init() {
  $("open").onclick = () => load($("pid").value.trim());
  $("pid").onkeydown = e => { if (e.key === "Enter") load($("pid").value.trim()); };
  const list = await api(CONFIG.paths.patients);        // optional endpoint; manual ID entry works without it
  if (Array.isArray(list)) clear($("plist"), list.map(p => h("option", { value: p.id }, p.name || "")));
  render(null, "Enter a patient ID and choose Open.");
}

async function load(id, tl) {
  if (!id) return;
  pid = id; $("pinfo").textContent = "Patient " + id; clear($("answer"));
  const [t, c] = await Promise.all([tl ? tl : api(CONFIG.paths.timeline(id)), api(CONFIG.paths.conflicts(id))]);
  if (!t && !c) return render(null, "Nothing was returned for this patient.");
  const a = { timeline: t ? normTimeline(t) : [], ...normConflicts(c || {}) };
  a.gate = await gateFor("analysis", { ...a, gate: (c && c.gate) || (t && t.gate) });
  render(a);
}

function render(a, why) {
  if (!a) {
    $("gate").className = "gate escalate";
    clear($("gate"), h("b", {}, "No analysis available"), h("p", {}, why || "Nothing can be concluded without data from the backend."));
    for (const id of ["timeline", "conflicts", "meds", "missing", "pending", "review"]) clear($(id), empty("No data."));
    return;
  }
  const g = a.gate, labels = { proceed: "Evidence is consistent", caveats: "Proceed with caution", escalate: "Stop: clinician review required" };
  $("gate").className = "gate " + g.decision;
  clear($("gate"), h("b", {}, labels[g.decision] || "Unknown safety status"),
    g.reasons.length ? h("ul", {}, g.reasons.map(r => h("li", {}, r.text))) : null,
    g.decision !== "proceed" ? h("p", {}, "Unresolved items are shown as unresolved. MEDUSA-X does not choose between conflicting sources.") : null);

  const tagText = { supported: "Supported", conflict: "Conflicting", missing: "Missing detail" };
  clear($("timeline"), a.timeline.length ? a.timeline.map(t => {
    const st = tagText[t.status] ? t.status : "unverified";
    return h("li", { class: st }, h("div", { class: "date" }, t.date || "Date not documented"), h("div", {}, t.event),
      h("span", { class: "tag " + st }, tagText[st] || "Unverified"), " ", t.source ? src(t.source) : null);
  }) : empty("No timeline events returned."));

  clear($("conflicts"), a.conflicts.length ? a.conflicts.map(c => h("div", { class: "item " + (c.severity || "") },
    h("strong", {}, c.title), " ", c.severity === "high" ? h("span", { class: "tag high" }, "High risk") : null,
    c.claims.map(k => h("p", {}, `“${k.text}” `, k.source ? src(k.source) : null)), srcs(c.sources))) : empty("No diagnosis conflicts reported."));

  clear($("meds"), a.medications.length ? a.medications.map(m => h("div", { class: "item " + (m.severity || "") },
    h("strong", {}, m.drug), h("p", {}, m.issue), srcs(m.sources))) : empty("No medication discrepancies reported."));

  const li = (x, none) => x.length ? x.map(m => h("li", {}, h("strong", {}, m.item || m.title || m.description || ""), m.why ? ": " + m.why : "")) : h("li", { class: "empty" }, none);
  clear($("missing"), li(a.missing, "Nothing reported missing."));
  clear($("pending"), li(a.pending, "Nothing reported pending."));
  renderReview(g);
}

function renderDocs() {
  clear($("docs"), uploaded.length ? uploaded.map(n => h("li", {}, n)) : h("li", { class: "empty" }, "No documents uploaded in this session."));
}

function renderReview(g) {
  const open = g.reasons.filter(r => r.severity === "high");
  const list = open.length ? open : (g.decision === "escalate" ? g.reasons : []);
  clear($("review"), list.length ? list.map(r => {
    const note = h("textarea", { placeholder: "Add context for the clinician (optional)", "aria-label": "Note for: " + r.text });
    const btn = h("button", {}, "Send to clinician");
    const msg = h("p", { class: "empty", role: "status" });
    btn.onclick = async () => {
      btn.disabled = true;
      const ok = await post(CONFIG.paths.escalate(pid), { issue_id: r.id, note: note.value });
      if (ok) { btn.textContent = "Sent for review"; msg.textContent = ""; }
      else { btn.disabled = false; msg.textContent = "Not sent: no escalation endpoint responded."; }
    };
    return h("div", { class: "item high" }, h("p", {}, h("strong", {}, r.text)), note, btn, msg);
  }) : empty("No issues need clinician review."));
}

const drop = $("drop"), fileIn = $("file");
drop.onclick = () => fileIn.click();
drop.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileIn.click(); } };
drop.ondragover = e => { e.preventDefault(); drop.classList.add("over"); };
drop.ondragleave = () => drop.classList.remove("over");
drop.ondrop = e => { e.preventDefault(); drop.classList.remove("over"); upload(e.dataTransfer.files); };
fileIn.onchange = () => upload(fileIn.files);

async function upload(files) {
  if (!files.length) return;
  if (!pid) return clear($("answer"), h("div", { class: "warn" }, "Enter a patient ID and choose Open before uploading."));
  const fd = new FormData(); fd.append("patient_id", pid); [...files].forEach(f => fd.append("files", f));
  const res = await api(CONFIG.paths.reconcile, { method: "POST", body: fd });
  if (!res) return $("docs").prepend(h("li", { class: "warn bad" }, "Upload failed. Nothing was added."));
  uploaded = uploaded.concat([...files].map(f => f.name)); renderDocs();
  load(pid, res);                                       // reconcile returns the timeline; conflicts are fetched separately
}

$("qa").onsubmit = async e => {
  e.preventDefault();
  const claim = $("q").value.trim();
  if (!claim || !pid) return clear($("answer"), h("div", { class: "warn" }, "Open a patient first, then type a statement to check."));
  clear($("answer"), empty("Checking the record…"));
  const raw = await post(CONFIG.paths.verify, { patient_id: pid, claims: [claim] });
  if (!raw) return clear($("answer"), h("div", { class: "warn bad", role: "alert" }, "No result: the backend did not respond."));
  const r = Array.isArray(raw) ? raw[0] : (arr(raw, "results", "claims")[0] || raw);
  const res = { claim, status: r.status || r.verdict, evidence: r.evidence || [], confidence: r.confidence, gate: r.gate };
  res.gate = await gateFor("answer", res);
  showResult(res);
};

function showResult(r) {
  // Shown as confirmed only if the backend says supported, evidence is cited, and the gate allows it.
  const confirmed = /^supported$/i.test(r.status || "") && r.evidence.length > 0 && r.gate.decision !== "escalate";
  r.status = confirmed ? "supported" : (/contradict|conflict/i.test(r.status || "") ? "conflict" : "insufficient");
  const passages = r.evidence.map(ev => h("p", {}, `“${ev.quote || ev.text || ""}” `, src(ev)));
  if (confirmed) return clear($("answer"), h("div", { class: "confirmed" }, h("span", { class: "tag supported" }, "Supported by the record"), h("p", {}, r.claim), passages));
  clear($("answer"),
    h("div", { class: "warn bad", role: "alert" }, h("strong", {}, "Not confirmed. "),
      r.status === "conflict" ? "Sources disagree with this statement or with each other." : "The record does not contain enough evidence to support this statement.", " A clinician should review it."),
    passages.length ? h("p", { class: "empty" }, "Related passages found in the record:") : null, passages);
}

renderDocs();
init();
