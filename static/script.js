/* ===========================================================================
   Cloud File Host - frontend logic (monolithic / same-origin)
   ---------------------------------------------------------------------------
   Author:        SYED SULAIMAN USMAN
   Last modified: April 18, 2026

   The UI and API live on the SAME domain, so we call the relative path
   "/upload" - no absolute URL, no CORS. The browser automatically attaches
   the login session cookie to this same-origin request.
   =========================================================================== */

(function () {
    "use strict";

    const form = document.getElementById("uploadForm");
    if (!form) return;

    const input = document.getElementById("fileInput");
    const fileChosen = document.getElementById("fileChosen");
    const dropLabel = document.getElementById("dropLabel");
    const button = document.getElementById("uploadBtn");
    const messageBox = document.getElementById("uploadMessage");

    function showMessage(text, type) {
        if (!messageBox) return;
        messageBox.innerHTML =
            '<div class="app-alert app-alert--' + type + '">' + text + "</div>";
    }

    // --- Reflect the chosen file name in the drop zone ---
    if (input && fileChosen) {
        input.addEventListener("change", function () {
            fileChosen.textContent = input.files.length
                ? input.files[0].name
                : "No file chosen";
        });
    }

    // --- Drag-and-drop visual feedback + assignment ---
    if (dropLabel && input) {
        ["dragenter", "dragover"].forEach(function (evt) {
            dropLabel.addEventListener(evt, function (e) {
                e.preventDefault();
                dropLabel.classList.add("dropzone--active");
            });
        });
        ["dragleave", "drop"].forEach(function (evt) {
            dropLabel.addEventListener(evt, function () {
                dropLabel.classList.remove("dropzone--active");
            });
        });
        dropLabel.addEventListener("drop", function (e) {
            e.preventDefault();
            if (e.dataTransfer.files.length) {
                input.files = e.dataTransfer.files;
                if (fileChosen) fileChosen.textContent = e.dataTransfer.files[0].name;
            }
        });
    }

    // --- The upload fetch (relative path, same-origin) ---
    form.addEventListener("submit", async function (event) {
        event.preventDefault();

        if (!input.files.length) {
            showMessage("Please choose a file first.", "error");
            return;
        }

        button.disabled = true;
        const originalLabel = button.innerHTML;
        button.innerHTML = "Uploading...";

        // FormData => the browser sets the correct multipart boundary itself.
        const formData = new FormData();
        formData.append("file", input.files[0]);

        try {
            const response = await fetch("/upload", {
                method: "POST",
                body: formData,
                // Same-origin: send cookies so the login session is recognised.
                credentials: "same-origin",
            });

            const data = await response.json().catch(function () {
                return {};
            });

            if (response.ok) {
                showMessage(data.message || "Uploaded successfully.", "success");
                // Refresh so the server-rendered file list shows the new file.
                setTimeout(function () {
                    window.location.reload();
                }, 600);
            } else if (response.status === 401) {
                // Session expired - send the user back to the login page.
                window.location.href = "/login";
            } else {
                showMessage(data.error || "Upload failed.", "error");
                button.disabled = false;
                button.innerHTML = originalLabel;
            }
        } catch (err) {
            showMessage("Network error - could not reach the server.", "error");
            button.disabled = false;
            button.innerHTML = originalLabel;
        }
    });
})();
