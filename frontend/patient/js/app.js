import { AuthApi, PatientApi, resetRequests } from "../../shared/js/api.js";
import { clear, el, greeting, initials, setText, todayLabel } from "../../shared/js/dom.js";
import { toast } from "../../shared/js/toast.js";

const pages = {
  dashboard: "Overview",
  records: "Medical records",
  appointments: "Appointments",
  doctors: "Find a doctor",
  assistant: "AI health assistant",
  consent: "Access & consent",
  profile: "My profile",
  history: "Medical history",
  audit: "Audit history",
};

const login = document.getElementById("login");
const app = document.getElementById("app");
const sidebar = document.getElementById("sidebar");
const backdrop = document.getElementById("sidebarBackdrop");
let currentUser = null;
let modalType = "";
let viewEpoch = 0;
let chatBusy = false;
let uploadBusy = false;
let authBusy = false;
let documentPoll;
let doctorDirectory = [];
let bookingBusy = false;
let recordRequest = 0;
let doctorRequest = 0;

function clearPatientData() {
  viewEpoch += 1;
  currentUser = null;
  clearInterval(documentPoll);
  chatBusy = false;
  uploadBusy = false;
  bookingBusy = false;
  doctorDirectory = [];
  for (const id of ["chatmessages", "recordsBody", "recentRecords", "auditRows", "consentRows", "modalFields", "upcomingList", "appointmentRows", "pastAppointments", "doctorGrid", "historyRows", "observationRows"]) clear(document.getElementById(id));
  for (const id of ["miniName", "miniAvatar", "topAvatar", "welcomeTitle", "chatContext", "profileName", "profileEmail", "profileMeta", "profileAvatar", "profileDob", "profileSex", "profileDemographics", "profileId", "vitalBp", "vitalHr", "vitalWeight", "vitalSpo2", "healthId", "vitalsTag", "demoBadge"] ) setText(id, "");
  document.getElementById("chatInput").value = "";
  for (const id of ["loginId", "regEmail", "recordSearch", "doctorSearch"]) document.getElementById(id).value = "";
  document.getElementById("recordType").value = "all";
  document.getElementById("doctorLocation").value = "";
  document.getElementById("doctorSpecialty").value = "";
  showError("loginError", "");
  showError("registerError", "");
  document.getElementById("loginPass").value = "";
  document.getElementById("regPassword").value = "";
  document.querySelector("#chatForm button").disabled = false;
  document.getElementById("modalSave").disabled = false;
  closeModal();
  document.getElementById("registerModal").hidden = true;
  setText("statRecords", "—");
  setText("statRecordsHint", "Sign in to view documents.");
  setText("assistantStatus", "Upload a document");
  setText("recentStatus", "Sign in to view documents.");
  setText("recordsStatus", "Sign in to view documents.");
  for (const id of ["statConsults", "statVisits", "statMeds", "chatReadyCount", "apptCount"]) setText(id, "—");
  for (const id of ["historyStatus", "appointmentStatus", "upcomingStatus", "consentStatus", "auditStatus", "doctorsStatus"]) setText(id, "Sign in to view your workspace.");
  document.getElementById("assignedOnly").checked = false;
  for (const id of ["doctorLocation", "doctorSpecialty"]) {
    const select = document.getElementById(id);
    while (select.options.length > 1) select.remove(1);
  }
}

window.addEventListener("session-expired", () => {
  resetRequests();
  clearPatientData();
  showLogin();
});

// Also clear private DOM when another tab changes accounts.
const sessionChannel = typeof BroadcastChannel === "function" ? new BroadcastChannel("careconnect-session") : null;
sessionChannel?.addEventListener("message", () => {
  resetRequests();
  clearPatientData();
  showLogin();
});

function showError(id, message) {
  const node = document.getElementById(id);
  node.textContent = message;
  node.classList.toggle("show", Boolean(message));
}

function go(id) {
  if (!pages[id]) return;
  document.querySelectorAll(".page").forEach((page) => {
    page.classList.toggle("active", page.id === id);
  });
  document.querySelectorAll(".nav button[data-page]").forEach((button) => {
    const active = button.dataset.page === id;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  setText("crumb", pages[id]);
  sidebar.classList.remove("open");
  backdrop.classList.remove("show");
  backdrop.hidden = true;
  window.scrollTo(0, 0);
  history.replaceState(null, "", `#${id}`);
  if (currentUser) {
    if (id === "history") loadHistory();
    if (id === "audit") loadAudit();
    if (id === "consent") loadConsent();
    if (id === "appointments") loadAppointments();
  }
}

function fillUser(user) {
  currentUser = user;
  const name = user.email.split("@")[0];
  const letters = initials(user.email);
  setText("miniName", user.email);
  setText("miniAvatar", letters);
  setText("topAvatar", letters);
  setText("welcomeTitle", `${greeting()}, ${name}`);
  setText("topDate", todayLabel());
  setText("welcomeDate", `◷  ${todayLabel()}`);
  setText("healthId", user.id);
  setText("chatContext", user.email);
  setText("profileName", name);
  setText("profileEmail", user.email);
  setText("profileMeta", `Patient · ${user.email}`);
  setText("profileAvatar", letters);
}

function emptyRow(targetId, message) {
  const target = document.getElementById(targetId);
  clear(target);
  target.append(el("p", { class: "sub", text: message }));
}

function status(id, message, error = false) {
  const node = document.getElementById(id);
  node.hidden = false;
  node.className = `status-banner ${error ? "error" : "empty"}`;
  node.textContent = message;
}

function label(code) {
  return String(code || "").replaceAll("_", " ");
}

function availabilityText(value) {
  if (!Array.isArray(value)) return typeof value === "string" ? value : "Availability not recorded";
  return value.map(slot => typeof slot === "string" ? slot : `${slot.day || ""} ${slot.start || ""}–${slot.end || ""} ${slot.timezone || ""}`).join(" · ");
}

function sourceLink(docId, text = "View source") {
  return el("a", { class: "link", href: `/api/v1/documents/${encodeURIComponent(docId)}/source`, target: "_blank", rel: "noopener", text });
}

function appointmentRow(appointment, canCancel = false) {
  const row = el("div", { class: "activity-row" }, [
    el("div", { class: "file-ico", text: "◷" }),
    el("div", {}, [el("b", { text: appointment.doctor_name || "Assigned practitioner" }),
      el("small", { text: `${new Date(appointment.scheduled_at).toLocaleString()} · ${appointment.specialty || ""}` }),
      el("p", { class: "sub", text: appointment.reason })]),
    el("span", { class: "tag blue", text: appointment.status }),
  ]);
  if (canCancel && ["REQUESTED", "CONFIRMED"].includes(appointment.status)) {
    const button = el("button", { class: "link", type: "button", text: "Cancel request" });
    button.addEventListener("click", async () => {
      const epoch = viewEpoch;
      button.disabled = true;
      try {
        await PatientApi.cancelAppointment(appointment.id);
        if (epoch !== viewEpoch) return;
        await Promise.all([loadAppointments(), loadDashboard()]);
      } catch (error) {
        if (epoch === viewEpoch) { toast(error.message); button.disabled = false; }
      }
    });
    row.append(button);
  }
  return row;
}

async function loadDashboard() {
  const epoch = viewEpoch;
  try {
    const result = await PatientApi.dashboard();
    if (epoch !== viewEpoch) return;
    setText("statRecords", result.stats.reports);
    setText("statConsults", result.stats.assigned_doctors);
    setText("statVisits", result.stats.upcoming_appointments);
    setText("statMeds", result.stats.indexed_reports);
    const list = document.getElementById("upcomingList"); clear(list);
    result.appointments.forEach(item => list.append(appointmentRow(item)));
    status("upcomingStatus", result.appointments.length ? "Your next requested or confirmed visits" : "No upcoming appointments.");
    const observations = result.observations || [];
    const latest = code => observations.find(item => item.code === code);
    const systolic = latest("systolic_bp"), diastolic = latest("diastolic_bp");
    setText("vitalBp", systolic && diastolic && systolic.document_id === diastolic.document_id ? `${systolic.value}/${diastolic.value}` : "—");
    setText("vitalHr", latest("fasting_glucose")?.value ?? "—");
    setText("vitalWeight", latest("hemoglobin")?.value ?? "—");
    setText("vitalSpo2", latest("hba1c")?.value ?? "—");
    setText("vitalsTag", observations.length ? "Latest documented values · see history for dates" : "No readings");
  } catch (error) {
    if (epoch === viewEpoch) status("upcomingStatus", error.message, true);
  }
}

async function loadRecords() {
  const epoch = viewEpoch;
  const request = ++recordRequest;
  try {
    const { documents } = await PatientApi.records();
    if (epoch !== viewEpoch || request !== recordRequest) return;
    const query = document.getElementById("recordSearch").value.trim().toLowerCase();
    const type = document.getElementById("recordType").value;
    const filtered = documents.filter(d => d.filename.toLowerCase().includes(query) && (type === "all" || d.media_type === type));
    const body = document.getElementById("recordsBody");
    clear(body);
    for (const doc of filtered) {
      const source = el("a", { class: "link", href: `/api/v1/documents/${encodeURIComponent(doc.id)}/source`, target: "_blank", rel: "noopener", text: "View source" });
      body.append(el("tr", {}, [
        el("td", { text: doc.filename }), el("td", { text: "Your upload" }),
        el("td", { text: new Date(doc.created_at).toLocaleDateString() }),
        el("td", { text: doc.media_type === "application/pdf" ? "PDF" : "TXT" }),
        el("td", {}, [el("span", { class: "tag blue", text: doc.state === "READY" ? "Indexed" : doc.state === "PROCESSING" ? "Indexing" : "Not indexed" }), el("small", { text: doc.error || `${doc.chunk_count} indexed chunks` })]),
        el("td", {}, [source]),
      ]));
    }
    if (!filtered.length) body.append(el("tr", {}, [el("td", { colspan: "6", class: "muted", text: "No matching documents. Add a PDF or TXT report to begin." })]));
    setText("statRecords", String(documents.length));
    setText("statRecordsHint", `${documents.filter(d => d.state === "READY").length} ready for the assistant`);
    setText("recordsStatus", "Only READY documents are searched. Re-upload a FAILED document to retry indexing.");
    document.getElementById("recordsStatus").className = "status-banner empty";
    setText("recentStatus", documents.length ? "Your latest uploaded documents" : "No documents yet. Open Medical records → Add record.");
    clear(document.getElementById("recentRecords"));
    for (const doc of documents.slice(0, 4)) {
      document.getElementById("recentRecords").append(el("div", { class: "record-row" }, [el("b", { text: doc.filename }), el("span", { class: "tag blue", text: doc.state === "READY" ? "Indexed" : doc.state === "PROCESSING" ? "Indexing" : "Not indexed" })]));
    }
    setText("chatReadyCount", String(documents.filter(d => d.state === "READY").length));
    setText("assistantStatus", documents.some(d => d.state === "READY") ? "Documents ready" : "Upload a document");
  } catch (error) {
    if (epoch !== viewEpoch || error.name === "AbortError") return;
    setText("recordsStatus", error.message);
    document.getElementById("recordsStatus").className = "status-banner error";
  }
}


async function loadAppointments() {
  const epoch = viewEpoch;
  status("appointmentStatus", "Loading appointments…");
  try {
    const { appointments } = await PatientApi.appointments();
    if (epoch !== viewEpoch) return;
    const future = document.getElementById("appointmentRows"), past = document.getElementById("pastAppointments");
    clear(future); clear(past); past.className = "";
    const upcoming = appointments.filter(item => new Date(item.scheduled_at) >= new Date() && ["REQUESTED", "CONFIRMED"].includes(item.status));
    upcoming.sort((a, b) => new Date(a.scheduled_at) - new Date(b.scheduled_at)).forEach(item => future.append(appointmentRow(item, true)));
    appointments.filter(item => !upcoming.includes(item)).forEach(item => past.append(appointmentRow(item, true)));
    if (!past.childElementCount) past.append(el("p", { class: "sub", text: "No past or cancelled appointments." }));
    setText("apptCount", `${upcoming.length} upcoming`);
    status("appointmentStatus", upcoming.length ? "Times are shown in your local timezone. Requests require practitioner confirmation." : "No upcoming appointments.");
  } catch (error) {
    if (epoch === viewEpoch) status("appointmentStatus", error.message, true);
  }
}

function renderDoctors() {
  const query = document.getElementById("doctorSearch").value.trim().toLowerCase();
  const specialty = document.getElementById("doctorSpecialty").value;
  const department = document.getElementById("doctorLocation").value;
  const assigned = document.getElementById("assignedOnly").checked;
  const doctors = doctorDirectory.filter(doc => (!assigned || doc.assigned) && (!specialty || doc.specialty === specialty) && (!department || doc.department === department) && `${doc.name} ${doc.specialty}`.toLowerCase().includes(query));
  const grid = document.getElementById("doctorGrid"); clear(grid);
  for (const doc of doctors) {
    const button = el("button", { class: "secondary", type: "button", text: "Request appointment" });
    button.addEventListener("click", () => openModal("appointment", doc.id));
    grid.append(el("div", { class: "card doctor-card" }, [
      el("h4", { text: doc.name }), el("p", { text: `${doc.specialty} · ${doc.department}` }),
      el("span", { class: "tag blue", text: doc.assigned ? "Your assigned doctor" : "Directory practitioner" }),
      el("p", { text: `${doc.qualifications} · ${doc.experience} years of experience` }),
      el("p", { text: doc.bio }), el("small", { text: availabilityText(doc.availability) }),
      doc.is_demo ? el("p", { class: "sub", text: "Fictional demonstration profile" }) : null, button,
    ]));
  }
  status("doctorsStatus", `${doctors.length} matching doctors. Booking requests do not grant medical-record access.`);
}

async function loadDoctors() {
  const epoch = viewEpoch, request = ++doctorRequest;
  status("doctorsStatus", "Loading doctor directory…");
  try {
    const { doctors } = await PatientApi.doctors();
    if (epoch !== viewEpoch || request !== doctorRequest) return;
    doctorDirectory = doctors;
    for (const [id, field] of [["doctorSpecialty", "specialty"], ["doctorLocation", "department"]]) {
      const select = document.getElementById(id), selected = select.value;
      while (select.options.length > 1) select.remove(1);
      [...new Set(doctors.map(doc => doc[field]).filter(Boolean))].sort().forEach(value => select.append(el("option", { value, text: value })));
      select.value = selected;
    }
    renderDoctors();
  } catch (error) {
    if (epoch === viewEpoch && request === doctorRequest) status("doctorsStatus", error.message, true);
  }
}

async function loadConsent() {
  const epoch = viewEpoch;
  status("consentStatus", "Loading sharing permissions…");
  try {
    const { consents } = await PatientApi.consents();
    if (epoch !== viewEpoch) return;
    const rows = document.getElementById("consentRows"); clear(rows);
    for (const consent of consents) {
      const fields = {};
      const row = el("div", { class: "card mt-10" }, [el("b", { text: consent.doctor_name }),
        el("p", { class: "sub", text: `${consent.specialty} · ${consent.assigned ? "Active assignment" : "No active assignment; consent alone does not enable access"}` })]);
      for (const [scope, title] of [["records", "Medical reports and sources"], ["clinical", "History, appointments and clinical notes"], ["ai", "AI questions using your reports"]]) {
        const input = el("input", { type: "checkbox", "aria-label": `${title} for ${consent.doctor_name}` });
        input.checked = consent[scope]; fields[scope] = input;
        row.append(el("label", { class: "consent-row" }, [el("span", { text: title }), input]));
      }
      fields.records.addEventListener("change", () => { if (!fields.records.checked) fields.ai.checked = false; });
      fields.ai.addEventListener("change", () => { if (fields.ai.checked) fields.records.checked = true; });
      const feedback = el("p", { class: "sub", role: "status" });
      const save = el("button", { class: "primary", type: "button", text: "Save permissions" });
      const revoke = el("button", { class: "secondary", type: "button", text: "Revoke all access" });
      const update = async revoked => {
        if (epoch !== viewEpoch) return;
        save.disabled = revoke.disabled = true;
        const body = Object.fromEntries(Object.entries(fields).map(([scope, input]) => [scope, revoked ? false : input.checked]));
        try {
          await PatientApi.saveConsent(consent.doctor_id, body);
          if (epoch !== viewEpoch) return;
          for (const [scope, value] of Object.entries(body)) fields[scope].checked = value;
          feedback.textContent = revoked ? "Access revoked. Subsequent doctor requests must pass the new permissions." : "Permissions saved.";
          loadAudit();
        } catch (error) {
          if (epoch === viewEpoch) feedback.textContent = error.message;
        } finally {
          if (epoch === viewEpoch) save.disabled = revoke.disabled = false;
        }
      };
      save.addEventListener("click", () => update(false)); revoke.addEventListener("click", () => update(true));
      row.append(el("div", { class: "modal-actions" }, [revoke, save]), feedback); rows.append(row);
    }
    status("consentStatus", consents.length ? "Each scope is enforced by the backend. AI requires report access. Changes apply to subsequent requests." : "No doctor assignments or permissions yet. Assignment is a controlled staff operation.");
  } catch (error) {
    if (epoch === viewEpoch) status("consentStatus", error.message, true);
  }
}

async function loadAudit() {
  const epoch = viewEpoch;
  status("auditStatus", "Loading account audit…");
  try {
    const { events } = await PatientApi.audit();
    if (epoch !== viewEpoch) return;
    const rows = document.getElementById("auditRows"); clear(rows);
    events.forEach(event => rows.append(el("div", { class: "activity-row" }, [el("div", { class: "file-ico", text: "◷" }), el("div", {}, [el("b", { text: event.action }), el("small", { text: `${new Date(event.createdAt).toLocaleString()} · ${event.outcome}` })])])));
    status("auditStatus", events.length ? "Latest recorded account events" : "No account events yet.");
  } catch (error) {
    if (epoch === viewEpoch) status("auditStatus", error.message, true);
  }
}

async function loadHistory() {
  const epoch = viewEpoch;
  status("historyStatus", "Loading medical history…");
  try {
    const result = await PatientApi.history();
    if (epoch !== viewEpoch) return;
    const rows = document.getElementById("historyRows"), measurements = document.getElementById("observationRows"); clear(rows); clear(measurements);
    const events = [
      ...result.history.map(item => ({ date: item.date, title: "Recorded history", text: item.summary || item.description || String(item) })),
      ...result.notes.map(item => ({ date: item.created_at, title: `Clinical note · ${item.doctor_name}`, text: item.content })),
      ...result.documents.map(item => ({ date: item.created_at, title: item.filename, text: `${item.state === "READY" ? "Indexed" : "Not indexed"} · ${item.chunk_count} chunks`, document_id: item.id })),
    ].sort((a, b) => new Date(b.date) - new Date(a.date));
    for (const event of events) rows.append(el("div", { class: "activity-row" }, [el("div", { class: "file-ico", text: "▤" }), el("div", {}, [el("b", { text: event.title }), el("small", { text: event.date ? new Date(event.date).toLocaleDateString() : "Date not recorded" }), el("p", { class: "sub", text: event.text }), event.document_id ? sourceLink(event.document_id) : null])]));
    if (!events.length) rows.append(el("p", { class: "sub", text: "No medical history or notes recorded." }));
    for (const item of result.observations) measurements.append(el("tr", {}, [el("td", { text: new Date(item.measured_at).toLocaleDateString() }), el("td", { text: label(item.code) }), el("td", { text: `${item.value} ${item.unit}` }), el("td", { text: item.reference_low != null && item.reference_high != null ? `${item.reference_low}–${item.reference_high} ${item.unit}` : "Not specified" }), el("td", {}, [sourceLink(item.document_id)])]));
    if (!result.observations.length) measurements.append(el("tr", {}, [el("td", { colspan: "5", text: "No structured observations recorded." })]));
    status("historyStatus", "Structured clinical notes are shown here, but are not embedded or searched by the AI assistant.");
  } catch (error) {
    if (epoch === viewEpoch) status("historyStatus", error.message, true);
  }
}

async function loadProfile() {
  const epoch = viewEpoch;
  try {
    const { profile } = await PatientApi.profile();
    if (epoch !== viewEpoch) return;
    const name = profile.name || currentUser.email;
    setText("miniName", name); setText("profileName", name);
    setText("welcomeTitle", `${greeting()}, ${name}`);
    setText("chatContext", `${name}${profile.is_demo ? " · Fictional demonstration patient" : ""}`);
    setText("profileMeta", profile.is_demo ? "Fictional synthetic patient · demonstration only" : "Patient account");
    setText("demoBadge", profile.is_demo ? "Synthetic demo profile" : "Patient profile");
    setText("profileDob", profile.dob || "Not on file"); setText("profileSex", profile.sex || "Not on file");
    setText("profileDemographics", Object.entries(profile.demographics || {}).map(([key, value]) => `${label(key)}: ${value}`).join(" · ") || "Not on file");
    setText("profileId", profile.user_id); setText("healthId", profile.user_id);
  } catch (error) {
    if (epoch === viewEpoch) setText("profileMeta", error.message);
  }
}

function openModal(type, doctorId = "") {
  if (bookingBusy) return toast("Wait for the current appointment request.");
  if (uploadBusy) return toast("Wait for the current upload to finish.");
  modalType = type;
  const title = document.getElementById("modalTitle");
  const desc = document.getElementById("modalDesc");
  const fields = document.getElementById("modalFields");
  clear(fields);
  if (type === "appointment") {
    title.textContent = "Book an appointment";
    desc.textContent = "Request a future appointment. Availability is informational; confirmation is required. A booking does not grant record access or create a clinical assignment.";
    const select = el("select", { id: "bookingDoctor" });
    select.append(el("option", { value: "", text: "Select a practitioner" }));
    for (const doc of doctorDirectory) select.append(el("option", { value: doc.id, text: `${doc.name} · ${doc.specialty}${doc.assigned ? " · Assigned" : ""}` }));
    select.value = doctorId;
    fields.append(
      el("div", { class: "field" }, [el("label", { for: "bookingDoctor", text: "Doctor" }), select]),
      el("div", { class: "field" }, [el("label", { for: "bookingTime", text: "Date and time (your local timezone)" }), el("input", { id: "bookingTime", type: "datetime-local", required: true })]),
      el("div", { class: "field" }, [el("label", { for: "bookingReason", text: "Reason for visit" }), el("textarea", { id: "bookingReason", maxlength: "1000", rows: "3" })]),
      el("p", { id: "bookingStatus", class: "sub", role: "status", text: doctorDirectory.length ? "Choose a doctor, time and reason." : "Doctor directory is unavailable. Close and retry after it loads." }),
    );
  } else {
    title.textContent = "Add a medical record";
    desc.textContent = "Upload a text-based PDF or UTF-8 TXT file (up to 10 MiB, 50 PDF pages). Scanned documents are not supported.";
    fields.append(
      el("div", { class: "field" }, [
        el("label", { for: "documentFile", text: "Medical document" }),
        el("input", { id: "documentFile", type: "file", accept: ".pdf,.txt,application/pdf,text/plain" }),
      ]),
      el("p", { id: "uploadStatus", role: "status", text: "Choose a file, then Upload and index." }),
      el("progress", { id: "uploadProgress", hidden: true, "aria-label": "Document upload and indexing in progress" }),
    );
  }
  setText("modalSave", type === "appointment" ? "Request appointment" : "Upload and index");
  const modal = document.getElementById("modal");
  modal.classList.add("show");
  modal.hidden = false;
}

function closeModal() {
  const modal = document.getElementById("modal");
  modal.classList.remove("show");
  modal.hidden = true;
}

function appendChat(text, mine = false) {
  const box = document.getElementById("chatmessages");
  box.append(el("div", { class: mine ? "bubble me" : "bubble", text }));
  box.scrollTop = box.scrollHeight;
  return box.lastElementChild;
}

async function sendChat(message) {
  if (chatBusy || !currentUser) return;
  const epoch = viewEpoch;
  const value = (message ?? document.getElementById("chatInput").value).trim();
  if (!value) return;
  document.getElementById("chatInput").value = "";
  appendChat(value, true);
  chatBusy = true;
  document.querySelector("#chatForm button").disabled = true;
  const pending = appendChat("Searching your documents and preparing an answer…");
  try {
    const result = await PatientApi.chat(value);
    if (epoch !== viewEpoch) return;
    pending.remove();
    const bubble = appendChat(result.answer);
    for (const citation of result.citations) {
      // Use only the authenticated local document route; never render model HTML or URLs.
      const url = `/api/v1/documents/${encodeURIComponent(citation.document_id)}/source${citation.page ? `#page=${Number(citation.page)}` : ""}`;
      bubble.append(el("details", {}, [
        el("summary", { text: `[${citation.label}] ${citation.title}${citation.page ? ` · page ${citation.page}` : ""}` }),
        el("p", { text: citation.excerpt }),
        el("a", { class: "link", href: url, target: "_blank", rel: "noopener", text: "Open source document" }),
      ]));
    }
    bubble.append(el("small", { class: "muted", text: `Request: ${result.request_id}` }));
    document.getElementById("chatmessages").scrollTop = document.getElementById("chatmessages").scrollHeight;
  } catch (error) {
    if (epoch !== viewEpoch || error.name === "AbortError") return;
    pending.textContent = error.message;
  } finally {
    if (epoch === viewEpoch) {
      chatBusy = false;
      document.querySelector("#chatForm button").disabled = false;
    }
  }
}

function showApp() {
  login.hidden = true;
  login.style.display = "none";
  app.hidden = false;
}

function showLogin() {
  app.hidden = true;
  login.hidden = false;
  login.style.display = "flex";
}

async function afterAuth(user) {
  if (user.role !== "PATIENT") {
    window.location.href = user.role === "PRACTITIONER" ? "/doctor/" : "/";
    return;
  }
  resetRequests(true);
  clearPatientData();
  sessionChannel?.postMessage("account-changed");
  fillUser(user);
  showApp();
  const hash = location.hash.replace("#", "");
  go(pages[hash] ? hash : "dashboard");
  await Promise.all([loadDashboard(), loadRecords(), loadAppointments(), loadDoctors(), loadConsent(), loadHistory(), loadProfile(), loadAudit()]);
}

document.getElementById("loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (authBusy) return;
  authBusy = true;
  showError("loginError", "");
  const email = document.getElementById("loginId").value.trim();
  const password = document.getElementById("loginPass").value;
  const button = document.getElementById("loginSubmit");
  button.disabled = true;
  try {
    const { user } = await AuthApi.login(email, password);
    await afterAuth(user);
  } catch (error) {
    showError("loginError", error.message);
  } finally {
    authBusy = false;
    button.disabled = false;
  }
});

document.getElementById("showRegister").addEventListener("click", () => {
  document.getElementById("registerModal").hidden = false;
  document.getElementById("registerModal").classList.add("show");
});

document.getElementById("cancelRegister").addEventListener("click", () => {
  document.getElementById("registerModal").hidden = true;
  document.getElementById("registerModal").classList.remove("show");
});

document.getElementById("registerForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (authBusy) return;
  authBusy = true;
  const button = event.currentTarget.querySelector("button[type=submit]");
  button.disabled = true;
  showError("registerError", "");
  try {
    const { user } = await AuthApi.register(
      document.getElementById("regEmail").value.trim(),
      document.getElementById("regPassword").value,
      "PATIENT",
    );
    document.getElementById("registerModal").hidden = true;
    await afterAuth(user);
  } catch (error) {
    showError("registerError", error.message);
  } finally {
    authBusy = false;
    button.disabled = false;
  }
});

document.querySelectorAll(".nav button[data-page]").forEach((button) => {
  button.addEventListener("click", () => go(button.dataset.page));
});

document.querySelectorAll("[data-go]").forEach((button) => {
  button.addEventListener("click", () => go(button.dataset.go));
});

document.querySelectorAll("[data-open]").forEach((button) => {
  button.addEventListener("click", () => openModal(button.dataset.open));
});

document.getElementById("menuBtn").addEventListener("click", () => {
  const open = sidebar.classList.toggle("open");
  backdrop.hidden = !open;
  backdrop.classList.toggle("show", open);
});

backdrop.addEventListener("click", () => {
  sidebar.classList.remove("open");
  backdrop.classList.remove("show");
  backdrop.hidden = true;
});

document.getElementById("supportBtn").addEventListener("click", () => {
  toast("Support centre is not available in this local demonstration.");
});

document.getElementById("notifyBtn").addEventListener("click", () => {
  toast("Review appointments and audit history for current account activity.");
});

document.getElementById("copyId").addEventListener("click", async () => {
  if (!currentUser) return;
  try { await navigator.clipboard.writeText(currentUser.id); toast("Account reference copied."); }
  catch { toast("Clipboard unavailable. Your account reference is shown in My profile."); }
});

document.getElementById("logoutBtn").addEventListener("click", async () => {
  resetRequests(true);
  clearPatientData();
  sessionChannel?.postMessage("account-changed");
  document.getElementById("logoutBtn").disabled = true;
  try {
    await AuthApi.logout();
    toast("Signed out.");
  } catch (error) {
    toast(`Local data cleared. Server sign-out failed: ${error.message}`);
  } finally {
    resetRequests();
    showLogin();
    document.getElementById("logoutBtn").disabled = false;
  }
});

document.getElementById("modalCancel").addEventListener("click", closeModal);
document.getElementById("refreshRecords").addEventListener("click", loadRecords);
document.getElementById("modalSave").addEventListener("click", async () => {
  if (modalType === "appointment") {
    if (bookingBusy || !currentUser) return;
    const epoch = viewEpoch, doctor_id = document.getElementById("bookingDoctor").value;
    const localTime = document.getElementById("bookingTime").value, reason = document.getElementById("bookingReason").value.trim();
    if (!doctor_id || !localTime || !reason) return setText("bookingStatus", "Choose a doctor, time and reason.");
    const date = new Date(localTime);
    if (!Number.isFinite(date.getTime()) || date <= new Date()) return setText("bookingStatus", "Choose a valid future time.");
    bookingBusy = true; document.getElementById("modalSave").disabled = true;
    setText("bookingStatus", "Submitting appointment request…");
    try {
      await PatientApi.bookAppointment({ doctor_id, scheduled_at: date.toISOString(), reason });
      if (epoch !== viewEpoch) return;
      setText("bookingStatus", "Appointment requested. Practitioner confirmation is required.");
      await Promise.all([loadAppointments(), loadDashboard(), loadAudit()]);
    } catch (error) { if (epoch === viewEpoch) setText("bookingStatus", error.message); }
    finally { if (epoch === viewEpoch) { bookingBusy = false; document.getElementById("modalSave").disabled = false; } }
    return;
  }
  if (uploadBusy || !currentUser) return;
  const file = document.getElementById("documentFile").files[0];
  if (!file) return setText("uploadStatus", "Choose a PDF or TXT file first.");
  if (file.size > 10 * 1024 * 1024) return setText("uploadStatus", "Maximum file size is 10 MiB.");
  const epoch = viewEpoch;
  uploadBusy = true;
  document.getElementById("modalSave").disabled = true;
  document.getElementById("uploadProgress").hidden = false;
  setText("uploadStatus", "Uploading and indexing… This can take a few minutes. You can view processing status in Medical records.");
  documentPoll = setInterval(loadRecords, 3000);
  try {
    const { document: doc, duplicate } = await PatientApi.upload(file);
    if (epoch !== viewEpoch) return;
    setText("uploadStatus", duplicate ? "This document is already indexed." : `${doc.filename}: ${doc.state} (${doc.chunk_count} chunks).`);
    toast("Document ready for questions.");
    await loadRecords();
  } catch (error) {
    if (epoch !== viewEpoch || error.name === "AbortError") return;
    setText("uploadStatus", error.message);
    await loadRecords();
  } finally {
    if (epoch === viewEpoch) {
      clearInterval(documentPoll);
      uploadBusy = false;
      document.getElementById("modalSave").disabled = false;
      const progress = document.getElementById("uploadProgress");
      if (progress) progress.hidden = true;
    }
  }
});

document.getElementById("refreshHistory").addEventListener("click", loadHistory);
document.getElementById("refreshAudit").addEventListener("click", loadAudit);

document.getElementById("chatForm").addEventListener("submit", (event) => {
  event.preventDefault();
  sendChat();
});

document.querySelectorAll("[data-ask]").forEach((button) => {
  button.addEventListener("click", () => sendChat(button.dataset.ask));
});

["recordSearch", "recordType"].forEach((id) => {
  document.getElementById(id).addEventListener("input", loadRecords);
  document.getElementById(id).addEventListener("change", loadRecords);
});

["doctorSearch", "doctorLocation", "doctorSpecialty"].forEach((id) => {
  document.getElementById(id).addEventListener("input", renderDoctors);
  document.getElementById(id).addEventListener("change", renderDoctors);
});

document.getElementById("assignedOnly").addEventListener("change", renderDoctors);

(async function boot() {
  try {
    const { user } = await AuthApi.me();
    await afterAuth(user);
  } catch {
    showLogin();
  }
})();
