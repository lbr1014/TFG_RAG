document.addEventListener("DOMContentLoaded", () => {
  const progressBox = document.getElementById("scraping-progress");
  const progressEl = progressBox?.querySelector(".progress");
  const nativeProgressEl = progressBox?.querySelector("progress");
  const bar = progressBox?.querySelector(".progress-bar");
  const text = progressBox?.querySelector(".progress-text");
  const cancelButton = document.getElementById("cancel-job-button");

  const scrapingForm = document.getElementById("scrapingForm");
  const vectorForm = document.getElementById("vectorForm");
  const markdownForm = document.getElementById("markdownForm");
  const uploadForm = document.getElementById("uploadForm");
  const uploadInput = document.getElementById("files");
  const uploadSummary = document.getElementById("upload-file-summary");

  let activeJob = null;

  function tr(key, params) {
    return window.pythiaTranslate ? window.pythiaTranslate(key, params) : key;
  }

  function errorSuffix(error) {
    return error ? ` Error: ${error}` : "";
  }

  function getCsrfToken(form) {
    return form?.querySelector('input[name="csrf_token"]')?.value
      || document.querySelector('input[name="csrf_token"]')?.value
      || "";
  }

  function csrfHeaders(form) {
    const token = getCsrfToken(form) || ensureCsrfToken();
    return token ? { "X-CSRFToken": token } : {};
  }

  function csrfFormData(form) {
    const data = new FormData();
    const token = getCsrfToken(form) || ensureCsrfToken();
    if (token) data.append("csrf_token", token);
    return data;
  }

  function ensureCsrfToken() {
    return document.querySelector('input[name="csrf_token"]')?.value || "";
  }

  function updateUploadSummary() {
    if (!uploadInput || !uploadSummary) return;

    const files = Array.from(uploadInput.files || []);
    if (files.length === 0) {
      uploadSummary.textContent = tr("docs.no_files_selected");
      return;
    }

    uploadSummary.textContent = files.length === 1
      ? files[0].name
      : tr("docs.files_selected", { count: files.length });
  }

  function toggleButtons(disabled) {
    // Permite subir PDF aunque haya un job activo, pero deshabilita los botones que inician procesos para evitar conflictos.
    [vectorForm, markdownForm, scrapingForm].forEach((form) => {
      form?.querySelectorAll("button").forEach((button) => {
        if (button === cancelButton) return;
        button.disabled = disabled;
      });
    });

    // En el panel de subida, deshabilitamos solo los botones que disparan procesos
    uploadForm?.querySelectorAll("button").forEach((button) => {
      if (button === cancelButton) return;
      const isProcessButton = button.form && ["scrapingForm", "markdownForm", "vectorForm"].includes(button.form.id);
      if (isProcessButton) button.disabled = disabled;
    });
  }

  uploadInput?.addEventListener("change", updateUploadSummary);
  updateUploadSummary();

  function showProgressBox() {
    if (!progressBox) return;
    progressBox.classList.remove("d-none");
    progressBox.style.display = "block";
  }

  function hideProgressBox() {
    if (!progressBox) return;
    progressBox.classList.add("d-none");
    progressBox.style.display = "none";
    if (text) text.textContent = "";
    if (bar) bar.style.width = "0%";
    if (progressEl) progressEl.setAttribute("aria-valuenow", "0");
    if (nativeProgressEl) nativeProgressEl.value = 0;
  }

  function showToast(title, message, variant = "success") {
    const container = document.getElementById("pythia-toast-container");
    if (!container || !window.bootstrap?.Toast) return;

    const toastEl = document.createElement("div");
    toastEl.className = `toast align-items-center text-bg-${variant} border-0`;
    toastEl.role = "status";
    toastEl.ariaLive = "polite";
    toastEl.ariaAtomic = "true";
    toastEl.innerHTML = `
      <div class="d-flex">
        <div class="toast-body">
          <strong class="me-2">${title}</strong>${message || ""}
        </div>
        <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
      </div>`;

    container.appendChild(toastEl);
    const toast = new window.bootstrap.Toast(toastEl, { delay: 4500 });
    toastEl.addEventListener("hidden.bs.toast", () => toastEl.remove());
    toast.show();
  }

  function setCancelVisible(visible) {
    if (!cancelButton) return;
    cancelButton.classList.toggle("d-none", !visible);
    cancelButton.disabled = false;
  }

  function setActiveJob(type, jobId) {
    activeJob = type && jobId ? { type, jobId: String(jobId) } : null;
    if (activeJob) {
      localStorage.setItem("admin_active_job_type", activeJob.type);
      localStorage.setItem("admin_active_job_id", activeJob.jobId);
      setCancelVisible(true);
      return;
    }

    localStorage.removeItem("admin_active_job_type");
    localStorage.removeItem("admin_active_job_id");
    setCancelVisible(false);
  }

  function setUIRunning(message) {
    showProgressBox();
    if (text) text.textContent = message;
    if (bar) {
      bar.classList.add("is-indeterminate");
      bar.classList.add("progress-bar-striped", "progress-bar-animated");
      bar.style.width = "0%";
    }
    if (progressEl) progressEl.setAttribute("aria-valuenow", "0");
    if (nativeProgressEl) nativeProgressEl.value = 0;
    toggleButtons(true);
  }

  function setUIProgress(percent, message) {
    if (!progressBox) return;
    showProgressBox();
    const boundedPercent = Math.max(0, Math.min(100, percent));
    if (bar) {
      bar.classList.remove("is-indeterminate");
      bar.classList.remove("progress-bar-animated");
      bar.style.width = `${boundedPercent}%`;
    }
    if (progressEl) progressEl.setAttribute("aria-valuenow", String(boundedPercent));
    if (nativeProgressEl) nativeProgressEl.value = boundedPercent;
    if (text) text.textContent = message;
  }

  function setUIIndeterminate(message) {
    showProgressBox();
    if (bar) {
      bar.classList.add("is-indeterminate");
      bar.classList.add("progress-bar-striped", "progress-bar-animated");
      bar.style.width = "0%";
    }
    if (progressEl) progressEl.setAttribute("aria-valuenow", "0");
    if (nativeProgressEl) nativeProgressEl.value = 0;
    if (text) text.textContent = message;
  }

  function setUIDone(message) {
    setUIProgress(100, message);
    showToast(tr("jobs.done_generic"), message || tr("jobs.done_generic"), "success");
    setActiveJob(null, null);
    hideProgressBox();
    window.setTimeout(() => window.location.reload(), 600);
  }

  function setUICancelled(message) {
    setUIProgress(0, message);
    showToast(tr("jobs.cancelled_generic"), message || tr("jobs.cancelled_generic"), "secondary");
    setActiveJob(null, null);
    toggleButtons(false);
    hideProgressBox();
  }

  function setUIFailed(message) {
    showProgressBox();
    if (bar) {
      bar.style.width = "100%";
    }
    if (progressEl) progressEl.setAttribute("aria-valuenow", "100");
    if (nativeProgressEl) nativeProgressEl.value = 100;
    if (text) text.textContent = message;
    showToast(tr("jobs.failed_generic"), message || tr("jobs.failed_generic"), "danger");
    setActiveJob(null, null);
    toggleButtons(false);
    hideProgressBox();
  }

  async function fetchJson(url, options = {}) {
    const headers = {
      Accept: "application/json",
      ...(options.headers || {}),
    };

    const response = await fetch(url, {
      ...options,
      headers,
    });

    let data = {};
    try {
      data = await response.json();
    } catch (error) {
      data = {};
    }

    if (!response.ok) {
      throw new Error(data.error || `HTTP ${response.status}`);
    }

    return data;
  }

  async function pollVectorJob(jobId) {
    const statusUrl = `/admin/vector-db/status/${jobId}`;

    while (true) {
      try {
        const data = await fetchJson(statusUrl);
        const status = data.status;
        const hasProgress = data.progress !== null && data.progress !== undefined;
        const progress = hasProgress ? Number(data.progress) : 0;
        const currentDoc = data.current_doc;

        if (status === "running" || status === "queued") {
          const message = currentDoc
            ? tr("vector.updating_doc", { progress, name: currentDoc })
            : tr("vector.updating", { progress });
          if (hasProgress) setUIProgress(progress, message);
          else setUIIndeterminate(message);
          await new Promise((resolve) => window.setTimeout(resolve, 1000));
          continue;
        }

        if (status === "done") {
          setUIDone(tr("vector.done_ui"));
          return;
        }

        if (status === "cancelled") {
          setUICancelled(tr("vector.cancelled_ui"));
          return;
        }

        if (status === "failed") {
          setUIFailed(tr("vector.failed_ui", { error_suffix: errorSuffix(data.error) }));
          return;
        }

        setUIFailed(tr("vector.unknown_state"));
        return;
      } catch (error) {
        setUIFailed(tr("vector.status_error"));
        return;
      }
    }
  }

  async function startVectorUpdate(event) {
    event.preventDefault();
    if (!vectorForm) return;

    try {
      setUIRunning(tr("vector.starting_ui"));
      const data = await fetchJson(vectorForm.action, {
        method: "POST",
        body: new FormData(vectorForm),
      });

      if (!data.job_id) {
        setUIFailed(tr("vector.no_job_id"));
        return;
      }

      setActiveJob("vector", data.job_id);
      setUIProgress(0, tr("vector.updating", { progress: 0 }));
      pollVectorJob(data.job_id);
    } catch (error) {
      setUIFailed(tr("vector.start_error"));
    }
  }

  async function pollMarkdownJob(jobId) {
    const statusUrl = `/admin/documents/markdown/status/${jobId}`;

    while (true) {
      try {
        const data = await fetchJson(statusUrl);
        const status = data.status;
        const hasProgress = data.progress !== null && data.progress !== undefined;
        const progress = hasProgress ? Number(data.progress) : 0;
        const message = data.message || tr("markdown.converting_doc", { name: progress + "%" });

        if (status === "running" || status === "queued") {
          if (hasProgress) setUIProgress(progress, message);
          else setUIIndeterminate(message);
          await new Promise((resolve) => window.setTimeout(resolve, 1000));
          continue;
        }

        if (status === "done") {
          setUIDone(data.message || tr("markdown.done_stats", { count: 0 }));
          return;
        }

        if (status === "cancelled") {
          setUICancelled(data.message || tr("markdown.cancelled"));
          return;
        }

        if (status === "failed") {
          setUIFailed(`${data.message || tr("markdown.failed")}${errorSuffix(data.error)}`);
          return;
        }

        setUIFailed(tr("markdown.unknown_state"));
        return;
      } catch (error) {
        setUIFailed(tr("markdown.status_error"));
        return;
      }
    }
  }

  async function startMarkdownConversion(event) {
    event.preventDefault();
    if (!markdownForm) return;

    try {
      setUIRunning(tr("markdown.starting_ui"));
      const data = await fetchJson(markdownForm.action, {
        method: "POST",
        body: new FormData(markdownForm),
      });

      if (!data.job_id) {
        setUIFailed(tr("markdown.no_job_id"));
        return;
      }

      setActiveJob("markdown", data.job_id);
      setUIProgress(0, tr("markdown.starting_ui"));
      pollMarkdownJob(data.job_id);
    } catch (error) {
      setUIFailed(tr("markdown.start_error"));
    }
  }

  async function pollScrapingJob(jobId) {
    const statusUrl = `/admin/documents/web_scraping/status/${jobId}`;

    while (true) {
      try {
        const data = await fetchJson(statusUrl);
        const status = data.status;
        const hasProgress = data.progress !== null && data.progress !== undefined;
        const progress = hasProgress ? Number(data.progress) : 0;
        const message = data.message || tr("scraping.starting_ui");

        if (status === "running" || status === "queued") {
          if (hasProgress) setUIProgress(progress, message);
          else setUIIndeterminate(message);
          await new Promise((resolve) => window.setTimeout(resolve, 1000));
          continue;
        }

        if (status === "done") {
          setUIDone(tr("scraping.done_ui"));
          return;
        }

        if (status === "cancelled") {
          setUICancelled(tr("scraping.cancelled"));
          return;
        }

        if (status === "failed") {
          setUIFailed(tr("scraping.failed_ui", { error_suffix: errorSuffix(data.error) }));
          return;
        }

        setUIFailed(tr("scraping.unknown_state"));
        return;
      } catch (error) {
        setUIFailed(tr("scraping.status_error"));
        return;
      }
    }
  }

  async function startScraping(event) {
    event.preventDefault();
    if (!scrapingForm) return;

    try {
      setUIRunning(tr("scraping.starting_ui"));
      const data = await fetchJson(scrapingForm.action, {
        method: "POST",
        body: new FormData(scrapingForm),
      });

      if (!data.job_id) {
        setUIFailed(tr("scraping.no_job_id"));
        return;
      }

      setActiveJob("scraping", data.job_id);
      setUIProgress(0, tr("scraping.starting_ui"));
      pollScrapingJob(data.job_id);
    } catch (error) {
      setUIFailed(tr("scraping.start_error"));
    }
  }

  async function cancelActiveJob() {
    if (!activeJob || !cancelButton) return;

    cancelButton.disabled = true;
    try {
      if (activeJob.type === "vector") {
        await fetchJson(`/admin/vector-db/cancel/${activeJob.jobId}`, {
          method: "POST",
          headers: csrfHeaders(vectorForm),
          body: csrfFormData(vectorForm),
        });
        setUIProgress(bar ? parseInt(bar.style.width || "0", 10) || 0 : 0, tr("vector.cancelling"));
      } else if (activeJob.type === "markdown") {
        await fetchJson(`/admin/documents/markdown/cancel/${activeJob.jobId}`, {
          method: "POST",
          headers: csrfHeaders(markdownForm),
          body: csrfFormData(markdownForm),
        });
        setUIProgress(bar ? parseInt(bar.style.width || "0", 10) || 0 : 0, tr("markdown.cancelling"));
      } else if (activeJob.type === "scraping") {
        await fetchJson(`/admin/documents/web_scraping/cancel/${activeJob.jobId}`, {
          method: "POST",
          headers: csrfHeaders(scrapingForm),
          body: csrfFormData(scrapingForm),
        });
        setUIProgress(bar ? parseInt(bar.style.width || "0", 10) || 0 : 0, tr("scraping.cancelling"));
      }
    } catch (error) {
      cancelButton.disabled = false;
      setUIFailed(error?.message || tr("process.cancel_error"));
    }
  }

  vectorForm?.addEventListener("submit", startVectorUpdate);
  markdownForm?.addEventListener("submit", startMarkdownConversion);
  scrapingForm?.addEventListener("submit", startScraping);
  cancelButton?.addEventListener("click", cancelActiveJob);

  async function resumeAnyActiveJob() {
    const savedType = localStorage.getItem("admin_active_job_type");
    const savedId = localStorage.getItem("admin_active_job_id");
    if (savedType && savedId) {
      setActiveJob(savedType, savedId);
      setUIRunning(tr("process.resume_tracking"));
      if (savedType === "vector") return pollVectorJob(savedId);
      if (savedType === "markdown") return pollMarkdownJob(savedId);
      if (savedType === "scraping") return pollScrapingJob(savedId);
    }

    try {
      const data = await fetchJson("/admin/jobs/active");
      const active = data?.markdown || data?.vector || data?.scraping;
      if (!active) return;

      // Prioridad: markdown > vector > scraping
      const pick = data.markdown || data.vector || data.scraping;
      const pickedType = data.markdown ? "markdown" : (data.vector ? "vector" : "scraping");
      const pickedId = pick?.job_id;
      if (!pickedId) return;

      setActiveJob(pickedType, pickedId);
      setUIRunning(tr("process.resume_tracking"));
      if (pickedType === "vector") return pollVectorJob(pickedId);
      if (pickedType === "markdown") return pollMarkdownJob(pickedId);
      return pollScrapingJob(pickedId);
    } catch (error) {
      // Silencioso: si falla, simplemente no reanudamos
    }
  }

  resumeAnyActiveJob();
});
