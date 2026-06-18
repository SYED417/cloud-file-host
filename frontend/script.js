/* ===========================================================================
   Cloud File Host - frontend upload logic
   ---------------------------------------------------------------------------
   Author:        SYED SULAIMAN USMAN
   Last modified: April 18, 2026

   Sends file uploads to the Flask backend hosted on Render.
   The backend URL is NEVER hardcoded to localhost. It is resolved at runtime
   from a configurable source so the same build works in every environment.
   =========================================================================== */

/**
 * Resolve the backend base URL.
 *
 * Resolution order:
 *   1. A global injected at build/deploy time (window.__API_URL__).
 *   2. The Next.js style build-time variable, if this file is bundled by a
 *      framework:  process.env.NEXT_PUBLIC_API_URL
 *   3. config.json fetched at runtime (the pattern for a plain static site).
 *
 * For a static Vercel deploy, set the value in frontend/config.json:
 *   { "apiBaseUrl": "https://cloud-file-host.onrender.com" }
 * For a Next.js deploy, set NEXT_PUBLIC_API_URL in Vercel's env settings.
 */
async function resolveApiUrl() {
    if (typeof window !== "undefined" && window.__API_URL__) {
        return window.__API_URL__;
    }
    if (typeof process !== "undefined" && process.env && process.env.NEXT_PUBLIC_API_URL) {
        return process.env.NEXT_PUBLIC_API_URL;
    }
    const cfg = await fetch("config.json").then((r) => r.json());
    return (cfg.apiBaseUrl || "").replace(/\/$/, ""); // strip trailing slash
}

/**
 * Upload a single file to the Render backend.
 *
 * @param {File}   file   The file object from an <input type="file">.
 * @param {string} token  The bearer token returned by POST /api/login.
 * @returns {Promise<object>} The parsed JSON response from the backend.
 */
async function uploadFile(file, token) {
    const apiUrl = await resolveApiUrl();
    if (!apiUrl) {
        throw new Error("Backend API URL is not configured.");
    }

    // multipart/form-data: do NOT set Content-Type manually. The browser adds
    // the correct multipart boundary automatically for a FormData body.
    const formData = new FormData();
    formData.append("file", file);

    const response = await fetch(`${apiUrl}/api/upload`, {
        method: "POST",
        headers: {
            // Token-based auth — no cookies, so this works cleanly cross-origin.
            Authorization: `Bearer ${token}`,
        },
        body: formData,
    });

    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
        // Surface the backend's error message to the caller.
        throw new Error(data.error || `Upload failed (HTTP ${response.status}).`);
    }
    return data;
}

// Example wiring to an upload form (ids match index.html in this folder).
document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("uploadForm");
    if (!form) return;

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const input = document.getElementById("fileInput");
        const token = localStorage.getItem("cfh_token");

        if (!input.files.length) return;
        if (!token) {
            alert("Please log in first.");
            return;
        }

        try {
            const result = await uploadFile(input.files[0], token);
            alert(result.message || "Uploaded successfully.");
            input.value = "";
        } catch (err) {
            alert(err.message);
        }
    });
});
