import { AuthApi, PatientApi } from "../../shared/js/api.js";
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
};

const login = document.getElementById("login");
const app = document.getElementById("app");
const sidebar = document.getElementById("sidebar");
const backdrop = document.getElementById("sidebarBackdrop");
let currentUser = null;
let modalType = "";

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
  setText("healthId", "Not issued yet");
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

async function loadPlaceholder(loader, statusId, emptyId, emptyMessage) {
  const status = document.getElementById(statusId);
  if (status) {
    status.className = "status-banner loading";
    status.textContent = "Checking API…";
  }
  try {
    await loader();
    if (status) {
      status.className = "status-banner empty";
      status.textContent = emptyMessage;
    }
  } catch (error) {
    if (status) {
      status.className = "status-banner error";
      status.textContent =
        error.status === 501
          ? emptyMessage
          : error.message;
    }
    if (emptyId) emptyRow(emptyId, error.status === 501 ? emptyMessage : "Unable to load this section.");
  }
}

async function loadDashboard() {
  await Promise.all([
    loadPlaceholder(PatientApi.records, "recentStatus", "recentRecords", "No records yet. Uploads arrive in a later milestone."),
    loadPlaceholder(PatientApi.appointments, "upcomingStatus", "upcomingList", "No upcoming appointments."),
    loadPlaceholder(PatientApi.observations, "recentStatus", null, "No records yet. Uploads arrive in a later milestone."),
  ]);
  setText("statRecords", "—");
  setText("statConsults", "—");
  setText("statVisits", "—");
  setText("statMeds", "—");
}

async function loadRecords() {
  await loadPlaceholder(
    PatientApi.records,
    "recordsStatus",
    "recordsBody",
    "No matching records found. The records API is not implemented in M1.",
  );
  const body = document.getElementById("recordsBody");
  if (!body.childElementCount) {
    const row = el("tr");
    const cell = el("td", { class: "muted", colspan: "6", text: "No matching records found." });
    row.append(cell);
    body.append(row);
  }
}

async function loadAppointments() {
  await loadPlaceholder(
    PatientApi.appointments,
    "appointmentStatus",
    "appointmentRows",
    "No appointments yet.",
  );
  setText("apptCount", "0 scheduled");
}

async function loadDoctors() {
  await loadPlaceholder(
    PatientApi.doctors,
    "doctorsStatus",
    "doctorGrid",
    "Nearby search ships with PostGIS in a later milestone.",
  );
}

async function loadConsent() {
  await loadPlaceholder(
    PatientApi.consents,
    "consentStatus",
    "consentRows",
    "No provider permissions yet.",
  );
  const status = document.getElementById("auditStatus");
  status.className = "status-banner loading";
  status.textContent = "Loading audit log…";
  try {
    const { events } = await PatientApi.audit();
    clear(document.getElementById("auditRows"));
    if (!events.length) {
      status.className = "status-banner empty";
      status.textContent = "No audit events yet.";
      return;
    }
    status.hidden = true;
    const list = document.getElementById("auditRows");
    for (const event of events) {
      list.append(
        el("div", { class: "activity-row" }, [
          el("div", { class: "file-ico", text: "◷" }),
          el("div", {}, [
            el("b", { text: event.action }),
            el("small", { text: `${new Date(event.createdAt).toLocaleString()} · ${event.outcome}` }),
          ]),
        ]),
      );
    }
  } catch (error) {
    status.className = "status-banner error";
    status.textContent = error.message;
  }
}

function openModal(type) {
  modalType = type;
  const title = document.getElementById("modalTitle");
  const desc = document.getElementById("modalDesc");
  const fields = document.getElementById("modalFields");
  clear(fields);
  if (type === "appointment") {
    title.textContent = "Book an appointment";
    desc.textContent = "Booking is not available until the appointments API is implemented.";
    fields.append(
      el("div", { class: "field" }, [
        el("label", { for: "f1", text: "Doctor / specialist" }),
        el("input", { id: "f1", disabled: true, placeholder: "Directory not connected" }),
      ]),
      el("div", { class: "field" }, [
        el("label", { for: "f2", text: "Appointment date" }),
        el("input", { id: "f2", type: "date", disabled: true }),
      ]),
    );
  } else {
    title.textContent = "Add a medical record";
    desc.textContent = "File uploads are not available in M1.";
    fields.append(
      el("div", { class: "field" }, [
        el("label", { for: "f1", text: "Record title" }),
        el("input", { id: "f1", disabled: true, placeholder: "Available in the documents milestone" }),
      ]),
    );
  }
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
}

async function sendChat(message) {
  const value = (message ?? document.getElementById("chatInput").value).trim();
  if (!value) return;
  document.getElementById("chatInput").value = "";
  appendChat(value, true);
  try {
    await PatientApi.chat(value);
  } catch (error) {
    appendChat(
      error.status === 501
        ? "The AI assistant is not connected in M1. Retrieval-augmented generation will use your authorized records only."
        : error.message,
    );
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
  fillUser(user);
  showApp();
  const hash = location.hash.replace("#", "");
  go(pages[hash] ? hash : "dashboard");
  await loadDashboard();
  await loadRecords();
  await loadAppointments();
  await loadDoctors();
  await loadConsent();
}

document.getElementById("loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
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
  toast("Support centre is not connected in M1.");
});

document.getElementById("notifyBtn").addEventListener("click", () => {
  toast("Notifications are not connected in M1.");
});

document.getElementById("copyId").addEventListener("click", async () => {
  toast("A CareConnect ID has not been issued yet.");
});

document.getElementById("logoutBtn").addEventListener("click", async () => {
  try {
    await AuthApi.logout();
  } catch {
    /* still return to login */
  }
  showLogin();
  toast("Signed out.");
});

document.getElementById("modalCancel").addEventListener("click", closeModal);
document.getElementById("modalSave").addEventListener("click", () => {
  toast(modalType === "appointment" ? "Booking API is not available in M1." : "Document upload is not available in M1.");
  closeModal();
});

document.getElementById("editProfileBtn").addEventListener("click", () => {
  toast("Profile editing waits for the Patient FHIR resource.");
});

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
  document.getElementById(id).addEventListener("input", loadDoctors);
  document.getElementById(id).addEventListener("change", loadDoctors);
});

(async function boot() {
  try {
    const { user } = await AuthApi.me();
    await afterAuth(user);
  } catch {
    showLogin();
  }
})();
