import { AuthApi, DoctorApi } from "../../shared/js/api.js";
import { clear, el, greeting, initials, setText, todayLabel } from "../../shared/js/dom.js";
import { toast } from "../../shared/js/toast.js";

const pages = {
  dashboard: "Today",
  schedule: "Schedule",
  patients: "Patients",
  records: "Clinical notes",
  audit: "Access log",
  profile: "My profile",
};

const login = document.getElementById("login");
const app = document.getElementById("app");
const sidebar = document.getElementById("sidebar");
const backdrop = document.getElementById("sidebarBackdrop");

function showError(id, message) {
  const node = document.getElementById(id);
  node.textContent = message;
  node.classList.toggle("show", Boolean(message));
}

function go(id) {
  if (!pages[id]) return;
  document.querySelectorAll(".page").forEach((page) => page.classList.toggle("active", page.id === id));
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
  history.replaceState(null, "", `#${id}`);
}

function fillUser(user) {
  const name = user.email.split("@")[0];
  const letters = initials(user.email);
  setText("miniName", user.email);
  setText("miniAvatar", letters);
  setText("topAvatar", letters);
  setText("welcomeTitle", `${greeting()}, ${name}`);
  setText("topDate", todayLabel());
  setText("welcomeDate", `◷  ${todayLabel()}`);
  setText("profileName", name);
  setText("profileEmail", user.email);
  setText("profileMeta", `Practitioner · ${user.email}`);
  setText("profileAvatar", letters);
}

async function markPlaceholder(loader, statusId, message) {
  const status = document.getElementById(statusId);
  if (!status) return;
  status.className = "status-banner loading";
  status.textContent = "Checking API…";
  try {
    await loader();
    status.className = "status-banner empty";
    status.textContent = message;
  } catch (error) {
    status.className = error.status === 501 ? "status-banner empty" : "status-banner error";
    status.textContent = error.status === 501 ? message : error.message;
  }
}

async function loadAudit() {
  const status = document.getElementById("auditStatus");
  status.hidden = false;
  status.className = "status-banner loading";
  status.textContent = "Loading audit log…";
  try {
    const { events } = await DoctorApi.audit();
    const list = document.getElementById("auditRows");
    clear(list);
    if (!events.length) {
      status.className = "status-banner empty";
      status.textContent = "No audit events yet.";
      return;
    }
    status.hidden = true;
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
  if (user.role !== "PRACTITIONER" && user.role !== "ADMIN") {
    window.location.href = "/patient/";
    return;
  }
  fillUser(user);
  showApp();
  const hash = location.hash.replace("#", "");
  go(pages[hash] ? hash : "dashboard");
  await markPlaceholder(DoctorApi.schedule, "todayStatus", "No visits loaded. The schedule API is a placeholder in M1.");
  await markPlaceholder(DoctorApi.schedule, "scheduleStatus", "Schedule management is not implemented in M1.");
  await markPlaceholder(DoctorApi.patients, "patientsStatus", "Patient list waits for consent-aware APIs.");
  await loadAudit();
}

document.getElementById("loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  showError("loginError", "");
  const button = document.getElementById("loginSubmit");
  button.disabled = true;
  try {
    const { user } = await AuthApi.login(
      document.getElementById("loginId").value.trim(),
      document.getElementById("loginPass").value,
    );
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
      "PRACTITIONER",
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
document.getElementById("menuBtn").addEventListener("click", () => {
  const open = sidebar.classList.toggle("open");
  backdrop.hidden = !open;
  backdrop.classList.toggle("show", open);
});
backdrop.addEventListener("click", () => {
  sidebar.classList.remove("open");
  backdrop.hidden = true;
});
document.getElementById("supportBtn").addEventListener("click", () => toast("Support centre is not connected in M1."));
document.getElementById("logoutBtn").addEventListener("click", async () => {
  try {
    await AuthApi.logout();
  } catch {
    /* ignore */
  }
  showLogin();
});

(async function boot() {
  try {
    const { user } = await AuthApi.me();
    await afterAuth(user);
  } catch {
    showLogin();
  }
})();
