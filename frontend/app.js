/* ===========================================================================
   Cloud File Host - frontend logic
   ---------------------------------------------------------------------------
   Talks to the Flask backend's JSON API using a bearer token.
   The backend URL is read at runtime from config.json, so you can change it
   (when your EC2 IP changes) by editing that one file and redeploying.
   =========================================================================== */

// Will hold the backend base URL once config.json is loaded.
let API_BASE = "";

// The login token is kept in localStorage so a page refresh stays logged in.
const TOKEN_KEY = "cfh_token";
const getToken = () => localStorage.getItem(TOKEN_KEY);
const setToken = (t) => localStorage.setItem(TOKEN_KEY, t);
const clearToken = () => localStorage.removeItem(TOKEN_KEY);

// --- Small helpers to show/hide sections and messages ----------------------

function show(el) { el.classList.remove("d-none"); }
function hide(el) { el.classList.add("d-none"); }

function showMessage(text, type = "success") {
    const box = document.getElementById("message");
    box.innerHTML = `
        <div class="alert alert-${type} alert-dismissible fade show shadow-sm" role="alert">
            ${text}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>`;
}

// --- Status badge in the navbar --------------------------------------------

function setStatus(state) {
    const badge = document.getElementById("statusBadge");
    if (state === "online") {
        badge.className = "badge rounded-pill bg-success";
        badge.innerHTML = '<i class="bi bi-check-circle me-1"></i>Backend online';
    } else if (state === "offline") {
        badge.className = "badge rounded-pill bg-danger";
        badge.innerHTML = '<i class="bi bi-x-circle me-1"></i>Backend offline';
    } else {
        badge.className = "badge rounded-pill bg-secondary";
        badge.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>Checking…';
    }
}

// --- API calls --------------------------------------------------------------

// Generic fetch wrapper that attaches the bearer token and parses JSON.
async function api(path, options = {}) {
    const headers = options.headers || {};
    const token = getToken();
    if (token) headers["Authorization"] = "Bearer " + token;
    const res = await fetch(API_BASE + path, { ...options, headers });
    return res;
}

async function checkHealth() {
    try {
        const res = await fetch(API_BASE + "/api/health");
        if (res.ok) { setStatus("online"); return true; }
    } catch (e) { /* fall through */ }
    setStatus("offline");
    return false;
}

// --- View switching ---------------------------------------------------------

function showLoggedOut() {
    show(document.getElementById("loginView"));
    hide(document.getElementById("dashboardView"));
    hide(document.getElementById("logoutBtn"));
    hide(document.getElementById("userInfo"));
}

function showLoggedIn(email, isAdmin) {
    hide(document.getElementById("loginView"));
    show(document.getElementById("dashboardView"));
    const logout = document.getElementById("logoutBtn");
    const info = document.getElementById("userInfo");
    show(logout);
    show(info);
    info.innerHTML = `<i class="bi bi-person-circle me-1"></i>${email}` +
        (isAdmin ? ' <span class="badge bg-primary-subtle text-primary ms-1">admin</span>' : "");
    loadFiles();
}

// --- File list rendering ----------------------------------------------------

async function loadFiles() {
    const area = document.getElementById("fileListArea");
    const count = document.getElementById("fileCount");
    area.innerHTML = '<p class="text-secondary mb-0">Loading…</p>';

    const res = await api("/api/files");
    if (!res.ok) {
        area.innerHTML = '<p class="text-danger mb-0">Could not load files.</p>';
        return;
    }
    const data = await res.json();
    const files = data.files || [];

    if (files.length === 0) {
        count.classList.add("d-none");
        area.innerHTML = `
            <div class="text-center text-secondary py-5">
                <i class="bi bi-inbox display-3 d-block mb-3 opacity-50"></i>
                <p class="fw-medium mb-1">No files uploaded yet.</p>
                <p class="small mb-0">Use the form above to get started.</p>
            </div>`;
        return;
    }

    count.classList.remove("d-none");
    count.textContent = files.length + (files.length === 1 ? " file" : " files");

    const rows = files.map(f => `
        <tr>
            <td><a href="${f.url}" target="_blank" class="text-decoration-none fw-medium text-body">
                <i class="bi bi-file-earmark me-2 text-secondary"></i>${f.name}</a></td>
            <td class="text-secondary">${f.size}</td>
            <td class="text-secondary">${f.last_modified}</td>
            <td class="text-end">
                <a href="${f.url}" target="_blank" download class="btn btn-sm btn-outline-primary">
                    <i class="bi bi-download me-1"></i>Download</a>
                <button class="btn btn-sm btn-outline-danger" data-key="${f.key}" data-name="${f.name}">
                    <i class="bi bi-trash me-1"></i>Delete</button>
            </td>
        </tr>`).join("");

    area.innerHTML = `
        <div class="table-responsive">
            <table class="table table-striped table-hover align-middle mb-0">
                <thead class="table-light">
                    <tr><th>File name</th><th>Size</th><th>Last modified</th><th class="text-end">Actions</th></tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        </div>`;

    // Wire up the delete buttons.
    area.querySelectorAll("button[data-key]").forEach(btn => {
        btn.addEventListener("click", () => deleteFile(btn.dataset.key, btn.dataset.name));
    });
}

async function deleteFile(key, name) {
    if (!confirm(`Delete '${name}'? This cannot be undone.`)) return;
    const res = await api("/api/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key }),
    });
    const data = await res.json();
    if (res.ok) { showMessage(data.message, "success"); loadFiles(); }
    else { showMessage(data.error || "Delete failed.", "danger"); }
}

// --- Event handlers ---------------------------------------------------------

document.getElementById("loginForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("loginSubmit");
    btn.disabled = true;
    try {
        const res = await fetch(API_BASE + "/api/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                email: document.getElementById("email").value,
                password: document.getElementById("password").value,
            }),
        });
        const data = await res.json();
        if (res.ok) {
            setToken(data.token);
            showMessage("Logged in successfully.", "success");
            showLoggedIn(data.email, data.is_admin);
        } else {
            showMessage(data.error || "Login failed.", "danger");
        }
    } catch (err) {
        showMessage("Could not reach the backend. It may be offline.", "danger");
    } finally {
        btn.disabled = false;
    }
});

document.getElementById("uploadForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = document.getElementById("fileInput");
    if (!input.files.length) return;

    const btn = document.getElementById("uploadSubmit");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Uploading…';

    // multipart/form-data: do NOT set Content-Type manually; the browser adds
    // the correct boundary automatically when the body is a FormData object.
    const form = new FormData();
    form.append("file", input.files[0]);

    try {
        const res = await api("/api/upload", { method: "POST", body: form });
        const data = await res.json();
        if (res.ok) { showMessage(data.message, "success"); input.value = ""; loadFiles(); }
        else { showMessage(data.error || "Upload failed.", "danger"); }
    } catch (err) {
        showMessage("Upload failed: could not reach the backend.", "danger");
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-upload me-1"></i>Upload file';
    }
});

document.getElementById("logoutBtn").addEventListener("click", () => {
    clearToken();
    showMessage("You have been logged out.", "success");
    showLoggedOut();
});

// --- Startup ----------------------------------------------------------------

async function init() {
    // 1. Load the backend URL from config.json.
    try {
        const cfg = await fetch("config.json").then(r => r.json());
        API_BASE = (cfg.apiBaseUrl || "").replace(/\/$/, ""); // trim trailing slash
    } catch (e) {
        showMessage("Could not load config.json (backend URL).", "danger");
        return;
    }

    // 2. Check whether the backend is reachable.
    const online = await checkHealth();
    const offlineNotice = document.getElementById("offlineNotice");
    if (!online) {
        show(offlineNotice);
        showLoggedOut();
        return;
    }
    hide(offlineNotice);

    // 3. If we already have a token, verify it and skip straight to dashboard.
    if (getToken()) {
        const res = await api("/api/me");
        if (res.ok) {
            const me = await res.json();
            showLoggedIn(me.email, me.is_admin);
            return;
        }
        clearToken(); // token expired/invalid
    }
    showLoggedOut();
}

init();
