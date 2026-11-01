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
  const headers = { ...(options.headers || {}) };
  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  let res;
  try {
    res = await fetch(path, {
      credentials: "include",
      ...options,
      headers,
      body: options.body && !(options.body instanceof FormData) ? JSON.stringify(options.body) : options.body,
    });
  } catch {
    const error = new Error("Cannot reach the Care Connect API. Start the M1 backend and try again.");
    error.status = 0;
    throw error;
  }
  const data = await parseBody(res);
  if (!res.ok) {
    const error = new Error(data.error || `Request failed (${res.status})`);
    error.status = res.status;
    error.data = data;
    throw error;
  }
  return data;
}

export const AuthApi = {
  me: () => api("/api/v1/auth/me"),
  login: (email, password) => api("/api/v1/auth/login", { method: "POST", body: { email, password } }),
  register: (email, password, role) =>
    api("/api/v1/auth/register", { method: "POST", body: { email, password, role } }),
  logout: () => api("/api/v1/auth/logout", { method: "POST" }),
};

export const PatientApi = {
  records: () => api("/api/v1/records"),
  appointments: () => api("/api/v1/appointments"),
  doctors: () => api("/api/v1/doctors"),
  observations: () => api("/api/v1/observations"),
  consents: () => api("/api/v1/consents"),
  audit: () => api("/api/v1/audit"),
  chat: (message) => api("/api/v1/ai/chat", { method: "POST", body: { message } }),
};

export const DoctorApi = {
  schedule: () => api("/api/v1/schedule"),
  patients: () => api("/api/v1/patients"),
  appointments: () => api("/api/v1/appointments"),
  audit: () => api("/api/v1/audit"),
};
