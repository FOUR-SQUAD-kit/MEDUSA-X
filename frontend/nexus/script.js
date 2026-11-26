
const API = "";

const $ = (id) => document.getElementById(id);

let selectedPatient = null;
let currentAnalysis = null;
let historySelectedPatient = null;

const LAST_PATIENT_KEY = "medusax_last_selected_patient";

function rememberSelectedPatient(patient) {
    selectedPatient = patient;

    if (patient?.patient_id) {
        localStorage.setItem(LAST_PATIENT_KEY, patient.patient_id);
    }

    const selector = $("home-patient-selector");
    if (selector && patient?.patient_id) {
        selector.value = patient.patient_id;
    }

    if ($("selected-patient-name")) {
        $("selected-patient-name").textContent =
            patient?.patient_name || "Patient";
        $("selected-patient-id").textContent =
            patient?.patient_id || "";
        $("patient-description").textContent =
            "Selected patient: " + (patient?.patient_name || patient?.patient_id);
        $("open-patient-button").disabled = !patient?.patient_id;
    }
}

const STATUS_LABELS = {
    confirmed_documented: "Confirmed documented",
    historical: "Historical",
    contradicted: "Contradicted",
    missing: "Missing information",
    pending_verification: "Pending verification"
};

async function request(path, options = {}) {
    const response = await fetch(API + path, options);

    let data;
    try {
        data = await response.json();
    } catch {
        throw new Error("The server returned an invalid response.");
    }

    if (!response.ok) {
        throw new Error(data.detail || `Request failed (${response.status})`);
    }

    return data;
}

function makeElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined && text !== null) {
        element.textContent = String(text);
    }
    return element;
}

function addEmpty(container, message) {
    container.replaceChildren(makeElement("div", "empty-state", message));
}

function formatDate(value) {
    if (!value) return "Date not documented";

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return String(value);
    }

    return date.toLocaleDateString("en-IN", {
        day: "2-digit",
        month: "short",
        year: "numeric"
    });
}

function getPatientInfo(analysis) {
    const patient = analysis?.patient || {};
    return {
        id: patient.patient_id || selectedPatient?.patient_id || "Unknown",
        name: patient.patient_name || selectedPatient?.patient_name || "Patient"
    };
}

function getEntries(analysis) {
    return analysis?.truth_ledger?.entries || [];
}

function getEvents(analysis) {
    return analysis?.timeline?.events || [];
}

function getSummary(analysis) {
    return analysis?.summary || {};
}

function showSection(sectionId) {
    document.querySelectorAll(".page-section").forEach(section => {
        section.classList.add("hidden");
    });

    const section = $(sectionId);
    if (section) section.classList.remove("hidden");

    document.querySelectorAll(".nav-item").forEach(button => {
        button.classList.toggle(
            "active",
            button.dataset.section === sectionId
        );
    });

    const titles = {
        dashboard: "Intelligence Overview",
        patients: "Patient Directory",
        documents: "Document Analysis",
        "timeline-section": "Clinical Timeline",
        "ledger-section": "Clinical Truth Ledger",
        "patient-history": "Patient History",
        "patient-workspace": "Patient Workspace"
    };

    $("page-title").textContent = titles[sectionId] || "MEDUSA-X";
}

function navigateTo(sectionId) {
    if (sectionId === "documents") {
        showSection("dashboard");
        $("upload-zone").scrollIntoView({
            behavior: "smooth",
            block: "center"
        });
        return;
    }

    if (sectionId === "patients") {
        showSection("dashboard");
        $("patients").scrollIntoView({
            behavior: "smooth",
            block: "center"
        });
        return;
    }

    showSection(sectionId);

    if (sectionId === "patient-history") {
        loadPatientHistory();
    }
}

async function checkBackend() {
    try {
        await request("/health");
        $("api-status").textContent = "API connected";
    } catch {
        $("api-status").textContent = "API unavailable";
        $("api-status").previousElementSibling.style.background = "#ff818c";
    }
}

async function loadPatients() {
    const container = $("patient-list");
    addEmpty(container, "Loading synthetic patients...");

    try {
        const response = await request("/api/patients");
        const patients = response.patients || [];

        const selector = $("home-patient-selector");
        if (selector) {
            selector.replaceChildren(
                new Option("Select a patient", "")
            );

            patients.forEach(patient => {
                selector.add(new Option(
                    `${patient.patient_name || "Unnamed patient"} (${patient.patient_id})`,
                    patient.patient_id
                ));
            });

            selector.onchange = () => {
                const patient = patients.find(
                    item => item.patient_id === selector.value
                );

                if (patient) {
                    rememberSelectedPatient(patient);

                    const result = $("qa-result");
                    const questionInput =
                        document.querySelector("#clinical-qa-panel .qa-input");

                    if (result) {
                        result.replaceChildren();
                        result.textContent =
                            "Patient changed. Ask a new question to retrieve this patient's evidence.";
                    }

                    if (questionInput) {
                        questionInput.value = "";
                    }
                }
            };
        }

        const savedPatientId =
            localStorage.getItem(LAST_PATIENT_KEY) ||
            selectedPatient?.patient_id;

        const rememberedPatient = patients.find(
            patient => patient.patient_id === savedPatientId
        );

        if (rememberedPatient) {
            rememberSelectedPatient(rememberedPatient);
        }

        $("stat-patients").textContent = patients.length
            .toString()
            .padStart(2, "0");

        container.replaceChildren();

        if (!patients.length) {
            addEmpty(container, "No synthetic patients are available.");
            return;
        }

        patients.forEach(patient => {
            const card = makeElement("div", "patient-card");

            const initial = makeElement(
                "div",
                "patient-initial",
                (patient.patient_name || "P").charAt(0).toUpperCase()
            );

            const details = makeElement("div", "patient-details");
            details.append(
                makeElement("strong", "", patient.patient_name || "Unnamed patient"),
                makeElement("small", "", patient.patient_id)
            );

            const button = makeElement("button", "patient-open", "Open â†’");
            button.type = "button";
            button.addEventListener("click", () => openPatient(patient));

            card.append(initial, details, button);
            container.append(card);
        });

    } catch (error) {
        addEmpty(container, error.message);
    }
}

async function openPatient(patient) {
    rememberSelectedPatient(patient);

    $("selected-patient-name").textContent = patient.patient_name || "Patient";
    $("selected-patient-id").textContent = patient.patient_id || "";
    $("patient-description").textContent =
        "Loading the patient's clinical timeline and evidence-backed findings...";

    $("open-patient-button").disabled = true;
    $("upload-status").textContent = "";

    try {
        const response = await request(
            `/api/patients/${encodeURIComponent(patient.patient_id)}/analysis`
        );

        if (response.status !== "success" || !response.analysis) {
            throw new Error("The backend did not return a completed analysis.");
        }

        currentAnalysis = response.analysis;

        $("patient-description").textContent =
            "Clinical analysis loaded from the MEDUSA-X backend.";

        $("open-patient-button").disabled = false;

        renderAnalysis(currentAnalysis);

        showSection("patient-workspace");

    } catch (error) {
        currentAnalysis = null;
        $("patient-description").textContent = error.message;
        $("open-patient-button").disabled = true;
    }
}

function renderAnalysis(analysis) {
    const info = getPatientInfo(analysis);
    const events = getEvents(analysis);
    const entries = getEntries(analysis);
    const summary = getSummary(analysis);
    const counts = analysis.truth_ledger?.status_counts || {};

    $("workspace-patient-name").textContent = info.name;
    $("workspace-patient-id").textContent = info.id;
    $("timeline-patient").textContent = info.id;

    $("patient-events").textContent = events.length;
    $("patient-conflicts").textContent =
        (summary.conflicts?.total ?? Object.values(summary.conflicts || {}).reduce(
            (sum, value) => sum + (Number(value) || 0), 0
        ));

    $("patient-pending").textContent =
        counts.pending_verification ?? 0;

    $("patient-historical").textContent =
        counts.historical ?? 0;

    $("stat-events").textContent = events.length;

    $("stat-findings").textContent =
        (counts.missing || 0) + (counts.pending_verification || 0);

    $("stat-review").textContent =
        (counts.contradicted || 0) + (counts.pending_verification || 0);

    renderTimeline(events);
    renderLedger(entries, counts);
    renderFindings(entries);
    renderReview(entries, analysis);
}

function renderTimeline(events) {
    const container = $("timeline-content");
    container.replaceChildren();

    if (!events.length) {
        addEmpty(container, "No timeline events were returned.");
        return;
    }

    events.forEach(event => {
        const item = makeElement("div", "timeline-item");

        const date = makeElement(
            "div",
            "timeline-date",
            formatDate(event.event_date || event.date)
        );

        const description = makeElement(
            "div",
            "timeline-event",
            event.name || event.event || event.description || "Clinical event"
        );

        const metaParts = [];

        if (event.category) metaParts.push(event.category);
        if (event.page) metaParts.push("Page " + event.page);
        if (event.evidence) metaParts.push(event.evidence);

        const meta = makeElement(
            "div",
            "timeline-meta",
            metaParts.join(" Â· ") || "Source details not available"
        );

        item.append(date, description, meta);
        container.append(item);
    });
}

function renderLedger(entries, counts) {
    const summary = $("ledger-summary");
    const container = $("ledger-content");

    summary.replaceChildren();
    container.replaceChildren();

    const statuses = [
        ["confirmed_documented", "Confirmed"],
        ["historical", "Historical"],
        ["contradicted", "Contradicted"],
        ["missing", "Missing"],
        ["pending_verification", "Pending review"]
    ];

    statuses.forEach(([key, label]) => {
        const card = makeElement("div", "ledger-stat");
        card.append(
            makeElement("strong", "", counts[key] ?? 0),
            makeElement("small", "", label)
        );
        summary.append(card);
    });

    if (!entries.length) {
        addEmpty(container, "No Truth Ledger entries were returned.");
        return;
    }

    entries.forEach(entry => {
        const card = makeElement("article", "ledger-entry");

        const heading = makeElement(
            "h4",
            "",
            `${entry.subject || "Clinical record"}`
        );

        const status = entry.status || "pending_verification";

        const tag = makeElement(
            "span",
            `status-tag status-${status}`,
            STATUS_LABELS[status] || status
        );

        const statement = makeElement(
            "p",
            "",
            entry.statement || "No statement provided."
        );

        card.append(heading, tag, statement);

        const evidence = entry.evidence || [];

        evidence.forEach(item => {
            const source = makeElement(
                "p",
                "timeline-meta",
                `Source: ${item.document || item.doc || "Document not specified"}${item.page ? " Â· Page " + item.page : ""}`
            );
            card.append(source);
        });

        (entry.open_questions || []).forEach(question => {
            card.append(makeElement("p", "timeline-meta", "Review question: " + question));
        });

        container.append(card);
    });
}

function renderFindings(entries) {
    const container = $("patient-findings");
    container.replaceChildren();

    if (!entries.length) {
        addEmpty(container, "No findings returned.");
        return;
    }

    entries.forEach(entry => {
        const card = makeElement("div", "finding-card");

        const heading = makeElement(
            "h4",
            "",
            `${entry.subject_type || "Clinical item"} Â· ${entry.subject || "Unspecified"}`
        );

        const statement = makeElement(
            "p",
            "",
            entry.statement || "No additional details."
        );

        const status = makeElement(
            "span",
            `status-tag status-${entry.status || "missing"}`,
            STATUS_LABELS[entry.status] || entry.status || "Unspecified"
        );

        card.append(heading, statement, status);
        container.append(card);
    });
}

function renderReview(entries, analysis) {
    const container = $("clinician-review");
    container.replaceChildren();

    const reviewEntries = entries.filter(entry =>
        ["pending_verification", "contradicted", "missing"].includes(entry.status)
    );

    const warnings = analysis.quality_warnings || [];

    if (!reviewEntries.length && !warnings.length) {
        addEmpty(container, "No unresolved items were returned. This does not replace clinician review.");
        return;
    }

    reviewEntries.forEach(entry => {
        const card = makeElement("div", "review-card");

        card.append(
            makeElement("strong", "", entry.subject || "Clinical item"),
            makeElement(
                "p",
                "",
                entry.statement || STATUS_LABELS[entry.status] || "Requires review."
            )
        );

        container.append(card);
    });

    warnings.forEach(warning => {
        const card = makeElement("div", "review-card");
        card.append(
            makeElement("strong", "", "Data quality warning"),
            makeElement(
                "p",
                "",
                typeof warning === "string"
                    ? warning
                    : warning.message || JSON.stringify(warning)
            )
        );
        container.append(card);
    });
}

async function uploadDocument(file) {
    if (!file) return;

    const allowed = [".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp"];
    const extension = "." + file.name.split(".").pop().toLowerCase();

    if (!allowed.includes(extension)) {
        $("upload-status").textContent =
            "Unsupported file. Choose a PDF or supported image.";
        return;
    }

    const status = $("upload-status");
    status.textContent = "Uploading and analysing document...";

    const formData = new FormData();
    formData.append("file", file);

    try {
        const response = await request("/api/analyze/upload", {
            method: "POST",
            body: formData
        });

        if (response.status !== "success" || !response.analysis) {
            throw new Error("The server did not return a completed analysis.");
        }

        currentAnalysis = response.analysis;
        selectedPatient = {
            patient_id: response.patient_id,
            patient_name: response.patient_name ||
                response.analysis.patient?.patient_name ||
                response.patient_id
        };

        $("selected-patient-name").textContent = selectedPatient.patient_name;
        $("selected-patient-id").textContent = selectedPatient.patient_id;
        $("patient-description").textContent =
            "Analysis generated from " + response.filename;

        $("open-patient-button").disabled = false;

        renderAnalysis(currentAnalysis);

        status.textContent =
            "Document processed successfully. Clinician review is required.";

        await loadPatientHistory();
        await loadPatients();

        showSection("patient-workspace");

    } catch (error) {
        status.textContent = "Upload failed: " + error.message;
    }
}

function setupUpload() {
    const input = $("file-input");
    const zone = $("upload-zone");

    $("browse-button").addEventListener("click", () => input.click());

    input.addEventListener("change", () => {
        if (input.files.length) uploadDocument(input.files[0]);
        input.value = "";
    });

    zone.addEventListener("dragover", event => {
        event.preventDefault();
        zone.classList.add("dragover");
    });

    zone.addEventListener("dragleave", () => {
        zone.classList.remove("dragover");
    });

    zone.addEventListener("drop", event => {
        event.preventDefault();
        zone.classList.remove("dragover");

        const file = event.dataTransfer.files[0];
        if (file) uploadDocument(file);
    });
}

function setupNavigation() {
    document.querySelectorAll(".nav-item").forEach(button => {
        button.addEventListener("click", () => {
            navigateTo(button.dataset.section);
        });
    });

    document.querySelectorAll("[data-go]").forEach(button => {
        button.addEventListener("click", () => {
            navigateTo(button.dataset.go);
        });
    });

    $("open-patient-button").addEventListener("click", () => {
        if (currentAnalysis) {
            showSection("patient-workspace");
        }
    });
}



function setupClinicalQA() {
    const workspace = $("home-qa-container");
    if (!workspace) return;

    const panel = makeElement("section", "qa-panel");
    panel.id = "clinical-qa-panel";

    const style = document.createElement("style");
    style.textContent = `
        .qa-panel {
            margin-top: 28px;
            padding: 24px;
            border: 1px solid rgba(93, 190, 210, .22);
            border-radius: 18px;
            background: linear-gradient(145deg, #111f35, #142940);
        }
        .qa-panel h2 { color: #e8f5ff; margin: 0 0 8px; }
        .qa-subtitle { color: #9fb7ca; margin-bottom: 18px; }
        .qa-form { display: flex; gap: 10px; flex-wrap: wrap; }
        .qa-input {
            flex: 1; min-width: 220px; padding: 13px 15px;
            border-radius: 10px; border: 1px solid #36546b;
            background: #0c192a; color: #fff; font-size: 14px;
        }
        .qa-button {
            padding: 12px 20px; border: 0; border-radius: 10px;
            background: #25b8bd; color: #071c29;
            font-weight: 700; cursor: pointer;
        }
        .qa-button:disabled { opacity: .5; cursor: wait; }
        .qa-result { margin-top: 20px; color: #dceaf4; }
        .qa-answer {
            padding: 15px; border-radius: 10px;
            background: rgba(28, 53, 76, .8);
            line-height: 1.6; margin-bottom: 15px;
        }
        .qa-source {
            padding: 14px; margin-top: 10px;
            border: 1px solid #34536b; border-radius: 10px;
            background: rgba(9, 24, 40, .7);
        }
        .qa-source strong { color: #71d8dc; }
        .qa-meta { color: #9fb7ca; font-size: 12px; margin-top: 8px; }
        .qa-review {
            color: #ffd18a; padding: 12px;
            border-radius: 8px; background: rgba(140, 94, 32, .15);
            margin-top: 14px; font-size: 13px;
        }
    `;
    document.head.appendChild(style);

    const heading = makeElement("h2", "", "Clinical Question Assistant");
    const subtitle = makeElement(
        "p",
        "qa-subtitle",
        "Ask a question about this patient's clinical records. Responses are based on retrieved evidence."
    );

    const form = makeElement("form", "qa-form");

    const mode = makeElement("select", "qa-input");
    mode.setAttribute("aria-label", "Question answering mode");
    mode.append(
        new Option("RAG - Evidence Retrieval", "rag"),
        new Option("Agentic AI - Clinical Investigation", "agentic")
    );
    const input = makeElement("input", "qa-input");
    input.type = "text";
    input.placeholder = "Ask a clinical question...";
    input.required = true;
    input.maxLength = 1000;

    const button = makeElement("button", "qa-button", "Ask Question");
    button.type = "submit";

    const result = makeElement("div", "qa-result");
    result.id = "qa-result";
    result.setAttribute("aria-live", "polite");

    form.append(mode, input, button);
    panel.append(heading, subtitle, form, result);
    workspace.append(panel);

    form.addEventListener("submit", async event => {
        event.preventDefault();

        if (!selectedPatient?.patient_id) {
            result.textContent = "Please select a patient first.";
            return;
        }

        const question = input.value.trim();
        if (!question) return;

        button.disabled = true;
        button.textContent = "Searching records...";
        result.replaceChildren(
            makeElement("p", "", "Retrieving patient-specific evidence...")
        );

        try {
            const endpoint = mode.value === "agentic" ? "agent-ask" : "ask";

            const response = await request(
                `/api/patients/${encodeURIComponent(selectedPatient.patient_id)}/${endpoint}`,
                {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(
                        mode.value === "agentic"
                            ? { question }
                            : { question, top_k: 5 }
                    )
                }
            );

            result.replaceChildren();

            result.append(
                makeElement(
                    "h3",
                    "",
                    mode.value === "agentic" ? "Agentic AI Result" : "Retrieval Result"
                ),
                makeElement(
                    "div",
                    "qa-answer",
                    response.answer || "No answer was returned."
                )
            );

            const evidence = response.evidence || [];

            if (mode.value === "agentic") {
                const trace = response.tool_trace || [];

                if (trace.length) {
                    result.append(makeElement("h3", "", "Investigation Steps"));
                    trace.forEach(item => {
                        result.append(
                            makeElement(
                                "p",
                                "qa-meta",
                                `${item.tool}: ${item.status}`
                            )
                        );
                    });
                }
            }

            if (evidence.length) {
                result.append(makeElement("h3", "", "Retrieved Clinical Evidence"));

                evidence.forEach((item, index) => {
                    const source = makeElement("article", "qa-source");

                    source.append(
                        makeElement(
                            "strong",
                            "",
                            `Evidence ${index + 1}: ${item.document_name || "Unknown document"}`
                        ),
                        makeElement("p", "", item.quote || "No evidence text available."),
                        makeElement(
                            "div",
                            "qa-meta",
                            `Page ${item.page || "Not recorded"} ? Event date: ${formatDate(item.event_date)} ? Evidence ID: ${item.evidence_id || "Unavailable"}`
                        )
                    );

                    result.append(source);
                });
            } else {
                result.append(
                    makeElement(
                        "p",
                        "qa-review",
                        "No relevant evidence was retrieved for this patient."
                    )
                );
            }

            if (response.requires_clinician_review) {
                result.append(
                    makeElement(
                        "div",
                        "qa-review",
                        "Clinician review required. Retrieved evidence is not an independently verified clinical conclusion."
                    )
                );
            }

        } catch (error) {
            result.replaceChildren(
                makeElement("p", "qa-review", "Question failed: " + error.message)
            );
        } finally {
            button.disabled = false;
            button.textContent = "Ask Question";
        }
    });
}

async function init() {
    setupNavigation();
    setupUpload();
    setupClinicalQA();

    await checkBackend();
    await loadPatients();

    $("stat-events").textContent = "â€”";
    $("stat-findings").textContent = "â€”";
    $("stat-review").textContent = "â€”";
}

document.addEventListener("DOMContentLoaded", init);

// MEDUSA-X PATIENT REGISTRATION CONNECTION

// MEDUSA-X PATIENT REGISTRATION CONNECTION
(function setupPatientRegistration() {
    const button = document.getElementById("register-patient-button");
    const input = document.getElementById("register-patient-name");
    const status = document.getElementById("register-patient-status");

    if (!button || !input || !status) return;

    async function registerPatient() {
        const patientName = input.value.trim();

        if (!patientName) {
            status.textContent = "Please enter a patient name.";
            return;
        }

        button.disabled = true;
        status.textContent = "Registering patient...";

        try {
            const response = await fetch("/api/patients/register", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ patient_name: patientName })
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || "Registration failed.");
            }

            input.value = "";
            status.textContent =
                data.patient.patient_name + " registered successfully (" +
                data.patient.patient_id + ").";

            if (typeof loadPatients === "function") {
                await loadPatients();
            }

            const listResponse = await fetch("/api/patients");
            const listData = await listResponse.json();
            const count = listData.patients.length;

            const countElement = document.getElementById("patient-count");
            const statElement = document.getElementById("stat-patients");

            if (countElement) {
                countElement.textContent = count + " RECORDS";
            }

            if (statElement) {
                statElement.textContent = String(count).padStart(2, "0");
            }

        } catch (error) {
            status.textContent = error.message;
        } finally {
            button.disabled = false;
        }
    }

    button.addEventListener("click", registerPatient);

    input.addEventListener("keydown", function(event) {
        if (event.key === "Enter") registerPatient();
    });
})();


// MEDUSA-X: Uploaded report history
function formatHistoryTimestamp(value) {
    if (!value) return "Date unavailable";

    const date = new Date(value);
    return Number.isNaN(date.getTime())
        ? "Date unavailable"
        : date.toLocaleString("en-IN");
}

function renderHistoryDocuments(patient) {
    const container = $("history-document-list");
    if (!container) return;

    $("history-selected-name").textContent =
        patient.patient_name || "Patient document history";
    $("history-selected-id").textContent =
        patient.patient_id || "";

    if (patient.historyError) {
        addEmpty(container, "Unable to load this patient's documents.");
        return;
    }

    const reports = [...(patient.reports || [])].sort(
        (a, b) => new Date(b.uploaded_at || 0) - new Date(a.uploaded_at || 0)
    );

    if (!reports.length) {
        addEmpty(container, "No documents uploaded for this patient yet.");
        return;
    }

    const list = makeElement("div", "history-document-items");

    reports.forEach(report => {
        const item = makeElement("article", "history-document-item");

        const details = makeElement("div", "history-document-details");
        details.append(
            makeElement("strong", "", report.filename || "Unnamed document"),
            makeElement("small", "", "Uploaded: " + formatHistoryTimestamp(report.uploaded_at))
        );

        const metadata = makeElement("div", "history-document-meta");
        metadata.append(
            makeElement("span", "", "Last reviewed: Not recorded"),
            makeElement("span", "", "Status: " + (report.status || "Unknown"))
        );

        const link = document.createElement("a");
        link.className = "history-view-link";
        link.href = `/api/reports/${encodeURIComponent(report.report_id)}/file`;
        link.target = "_blank";
        link.rel = "noopener";
        link.textContent = "View report";

        item.append(details, metadata, link);
        list.append(item);
    });

    container.replaceChildren(list);
}

async function loadPatientHistory() {
    const patientContainer = $("history-patient-list");
    const countLabel = $("history-patient-count");

    if (!patientContainer || !countLabel) return;

    addEmpty(patientContainer, "Loading patient records...");
    $("history-document-list").textContent = "Loading document history...";

    try {
        const response = await request("/api/patients");
        const patients = response.patients || [];

        countLabel.textContent =
            `${patients.length} ${patients.length === 1 ? "PATIENT" : "PATIENTS"}`;

        if (!patients.length) {
            historySelectedPatient = null;
            addEmpty(patientContainer, "No registered patients found.");
            $("history-selected-name").textContent = "Patient document history";
            $("history-selected-id").textContent = "SELECT A PATIENT";
            addEmpty($("history-document-list"), "No patient records are available.");
            return;
        }

        const records = await Promise.all(
            patients.map(async patient => {
                try {
                    const result = await request(
                        `/api/patients/${encodeURIComponent(patient.patient_id)}/reports`
                    );

                    const reports = result.reports || [];
                    const latest = reports.reduce((current, report) => {
                        if (!current) return report;
                        return new Date(report.uploaded_at || 0) >
                            new Date(current.uploaded_at || 0)
                            ? report
                            : current;
                    }, null);

                    return { ...patient, reports, latestUpload: latest, historyError: false };
                } catch (error) {
                    console.error("Patient history load failed:", patient.patient_id, error);
                    return { ...patient, reports: [], latestUpload: null, historyError: true };
                }
            })
        );

        const previousId = historySelectedPatient?.patient_id;
        historySelectedPatient =
            records.find(patient => patient.patient_id === previousId) || records[0];

        const directory = makeElement("div", "history-patient-items");

        records.forEach(patient => {
            const card = makeElement("button", "history-patient-card");
            card.type = "button";
            card.classList.toggle(
                "active",
                patient.patient_id === historySelectedPatient.patient_id
            );

            const initial = makeElement(
                "div",
                "history-patient-initial",
                (patient.patient_name || "P").charAt(0).toUpperCase()
            );

            const details = makeElement("div", "history-patient-details");
            details.append(
                makeElement("strong", "", patient.patient_name || "Unnamed patient"),
                makeElement("small", "", patient.patient_id)
            );

            const summary = makeElement("div", "history-patient-summary");
            summary.append(
                makeElement("strong", "", patient.historyError
                    ? "Unavailable"
                    : `${patient.reports.length} documents`),
                makeElement("small", "", patient.latestUpload
                    ? "Latest: " + formatHistoryTimestamp(patient.latestUpload.uploaded_at)
                    : "No uploads yet")
            );

            card.append(initial, details, summary);
            card.addEventListener("click", () => {
                historySelectedPatient = patient;

                directory.querySelectorAll(".history-patient-card")
                    .forEach(button => button.classList.remove("active"));
                card.classList.add("active");

                renderHistoryDocuments(patient);
            });

            directory.append(card);
        });

        patientContainer.replaceChildren(directory);
        renderHistoryDocuments(historySelectedPatient);

    } catch (error) {
        console.error("Patient directory load failed:", error);
        addEmpty(patientContainer, "Unable to load patient records. Please try again.");
        addEmpty($("history-document-list"), "Document history is unavailable.");
    }
}
