document.addEventListener("DOMContentLoaded", () => {
  const progressBox = document.getElementById("scraping-progress");
  const bar = progressBox?.querySelector(".progress-bar");
  const text = progressBox?.querySelector(".progress-text");
  const cancelButton = document.getElementById("cancel-job-button");

  const scrapingForm = document.getElementById("scrapingForm");
  const vectorForm = document.getElementById("vectorForm");
  const markdownForm = document.getElementById("markdownForm");
  const uploadForm = document.getElementById("uploadForm");

  let activeJob = null;

  function tr(key, params) {
    return window.pythiaTranslate ? window.pythiaTranslate(key, params) : key;
  }

  function errorSuffix(error) {
    return error ? ` Error: ${error}` : "";
  }

  function toggleButtons(disabled) {
    uploadForm?.querySelectorAll("button").forEach((button) => {
      button.disabled = disabled;
    });
  }

  function showProgressBox() {
    if (!progressBox) return;
    progressBox.classList.remove("d-none");
    progressBox.style.display = "block";
  }

  function setCancelVisible(visible) {
    if (!cancelButton) return;
    cancelButton.classList.toggle("d-none", !visible);
    cancelButton.disabled = false;
  }

  function setActiveJob(type, jobId) {
    activeJob = type && jobId ? { type, jobId: String(jobId) } : null;
    if (activeJob) {
      sessionStorage.setItem("admin_active_job_type", activeJob.type);
      sessionStorage.setItem("admin_active_job_id", activeJob.jobId);
      setCancelVisible(true);
      return;
    }

    sessionStorage.removeItem("admin_active_job_type");
    sessionStorage.removeItem("admin_active_job_id");
    setCancelVisible(false);
  }

  function setUIRunning(message) {
    showProgressBox();
    if (text) text.textContent = message;
    if (bar) {
      bar.style.animation = "none";
      bar.style.width = "0%";
    }
    toggleButtons(true);
  }

  function setUIProgress(percent, message) {
    if (!progressBox || !bar) return;
    showProgressBox();
    bar.style.animation = "none";
    bar.style.width = `${Math.max(0, Math.min(100, percent))}%`;
    if (text) text.textContent = message;
  }

  function setUIDone(message) {
    setUIProgress(100, message);
    setActiveJob(null, null);
    window.setTimeout(() => window.location.reload(), 600);
  }

  function setUICancelled(message) {
    setUIProgress(0, message);
    setActiveJob(null, null);
    toggleButtons(false);
  }

  function setUIFailed(message) {
    showProgressBox();
    if (bar) {
      bar.style.animation = "none";
      bar.style.width = "100%";
    }
    if (text) text.textContent = message;
    setActiveJob(null, null);
    toggleButtons(false);
  }

  async function fetchJson(url, options = {}) {
    const response = await fetch(url, {
      headers: { Accept: "application/json" },
      ...options,
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
        const progress = Number(data.progress ?? 0);
        const currentDoc = data.current_doc;

        if (status === "running" || status === "queued") {
          const message = currentDoc
            ? tr("vector.updating_doc", { progress, name: currentDoc })
            : tr("vector.updating", { progress });
          setUIProgress(progress, message);
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
      const data = await fetchJson(vectorForm.action, { method: "POST" });

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
        const progress = Number(data.progress ?? 0);
        const message = data.message || tr("markdown.converting_doc", { name: progress + "%" });

        if (status === "running" || status === "queued") {
          setUIProgress(progress, message);
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
          setUIFailed(data.message || tr("markdown.failed"));
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
      const data = await fetchJson(markdownForm.action, { method: "POST" });

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
        const progress = Number(data.progress ?? 0);
        const message = data.message || tr("scraping.starting_ui");

        if (status === "running" || status === "queued") {
          setUIProgress(progress, message);
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
      const data = await fetchJson(scrapingForm.action, { method: "POST" });

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
        await fetchJson(`/admin/vector-db/cancel/${activeJob.jobId}`, { method: "POST" });
        setUIProgress(bar ? parseInt(bar.style.width || "0", 10) || 0 : 0, tr("vector.cancelling"));
      } else if (activeJob.type === "markdown") {
        await fetchJson(`/admin/documents/markdown/cancel/${activeJob.jobId}`, { method: "POST" });
        setUIProgress(bar ? parseInt(bar.style.width || "0", 10) || 0 : 0, tr("markdown.cancelling"));
      } else if (activeJob.type === "scraping") {
        await fetchJson(`/admin/documents/web_scraping/cancel/${activeJob.jobId}`, { method: "POST" });
        setUIProgress(bar ? parseInt(bar.style.width || "0", 10) || 0 : 0, tr("scraping.cancelling"));
      }
    } catch (error) {
      cancelButton.disabled = false;
      setUIFailed(error.message || tr("process.cancel_error"));
    }
  }

  vectorForm?.addEventListener("submit", startVectorUpdate);
  markdownForm?.addEventListener("submit", startMarkdownConversion);
  scrapingForm?.addEventListener("submit", startScraping);
  cancelButton?.addEventListener("click", cancelActiveJob);

  const savedType = sessionStorage.getItem("admin_active_job_type");
  const savedId = sessionStorage.getItem("admin_active_job_id");
  if (savedType && savedId) {
    setActiveJob(savedType, savedId);
    setUIRunning(tr("process.resume_tracking"));
    if (savedType === "vector") {
      pollVectorJob(savedId);
    } else if (savedType === "markdown") {
      pollMarkdownJob(savedId);
    } else if (savedType === "scraping") {
      pollScrapingJob(savedId);
    }
  }
});
