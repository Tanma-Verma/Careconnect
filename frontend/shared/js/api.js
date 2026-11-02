let csrfToken = "";
let generation = 0;
const pending = new Set();

export function resetRequests(keepCsrf = false) {
  generation += 1;
  for (const controller of pending) controller.abort();
  pending.clear();
  if (!keepCsrf) csrfToken = "";
}

async function parseBody(res) {
  const text = await res.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return { error: text };
  }
}

export async function api(path, options = {}) {
  const epoch = generation;
  const controller = new AbortController();
  pending.add(controller);
  const timer = setTimeout(() => controller.abort(), 240000);
  const headers = { "X-Requested-With": "CareConnect", ...(options.headers || {}) };
  if (csrfToken && (options.method || "GET") !== "GET") headers["X-CSRF-Token"] = csrfToken;
  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  try {
    const res = await fetch(path, {
      credentials: "include",
      ...options,
      signal: controller.signal,
      headers,
      body: options.body && !(options.body instanceof FormData) ? JSON.stringify(options.body) : options.body,
    });
    const data = await parseBody(res);
    if (epoch !== generation) throw new DOMException("Session changed", "AbortError");
    if (!res.ok) {
      const error = new Error(typeof data.error === "string" ? data.error : `Request failed (${res.status})`);
      error.status = res.status;
      error.data = data;
      if (res.status === 401 && !path.endsWith("/login")) window.dispatchEvent(new Event("session-expired"));
      throw error;
    }
    if (data.csrf_token) csrfToken = data.csrf_token;
    return data;
  } catch (cause) {
    if (epoch !== generation) throw new DOMException("Session changed", "AbortError");
    if (cause.status) throw cause;
    const error = new Error(controller.signal.aborted ? "Request timed out. Refresh the document list before retrying an upload." : "Cannot reach the CareConnect API. Check that the backend is running.");
    error.status = 0;
    throw error;
  } finally {
    clearTimeout(timer);
    pending.delete(controller);
  }
}

export const AuthApi = {
  me: () => api("/api/v1/auth/me"),
  login: (email, password) => api("/api/v1/auth/login", { method: "POST", body: { email, password } }),
  register: (email, password, role) =>
    api("/api/v1/auth/register", { method: "POST", body: { email, password, role } }),
  logout: () => api("/api/v1/auth/logout", { method: "POST" }),
};

export const PatientApi = {
  dashboard: () => api("/api/v1/patient/dashboard"),
  profile: () => api("/api/v1/patient/profile"),
  history: () => api("/api/v1/patient/history"),
  records: () => api("/api/v1/records"),
  upload: (file) => {
    const body = new FormData();
    body.append("file", file);
    return api("/api/v1/documents", { method: "POST", body });
  },
  appointments: () => api("/api/v1/patient/appointments"),
  bookAppointment: (body) => api("/api/v1/patient/appointments", { method: "POST", body }),
  cancelAppointment: (id) => api(`/api/v1/patient/appointments/${encodeURIComponent(id)}`, { method: "PATCH", body: { status: "CANCELLED" } }),
  doctors: (query = "") => api(`/api/v1/patient/doctors${query ? `?${query}` : ""}`),
  observations: () => api("/api/v1/patient/observations"),
  consents: () => api("/api/v1/patient/consents"),
  saveConsent: (id, body) => api(`/api/v1/patient/consents/${encodeURIComponent(id)}`, { method: "PUT", body }),
  audit: () => api("/api/v1/audit"),
  chat: (message) => api("/api/v1/ai/chat", { method: "POST", body: { message } }),
};

export const DoctorApi = {
  dashboard: () => api("/api/v1/doctor/dashboard"),
  profile: () => api("/api/v1/doctor/profile"),
  schedule: () => api("/api/v1/doctor/appointments"),
  patients: () => api("/api/v1/doctor/patients"),
  appointments: () => api("/api/v1/doctor/appointments"),
  audit: () => api("/api/v1/audit"),
};
