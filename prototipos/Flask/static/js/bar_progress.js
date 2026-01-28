document.addEventListener("DOMContentLoaded", () => {
  const progressBox = document.getElementById("scraping-progress");
  const bar = progressBox?.querySelector(".progress-bar");
  const text = progressBox?.querySelector(".progress-text");

  const scrapingForm = document.getElementById("scrapingForm");
  const vectorForm = document.getElementById("vectorForm");
  const uploadForm = document.getElementById("uploadForm");

  function setUIRunning(message) {
    if (progressBox) progressBox.style.display = "block";
    if (text) text.textContent = message;
    if (bar) {
      bar.style.animation = "none";
      bar.style.width = "0%";
    }
    uploadForm?.querySelectorAll("button").forEach((b) => (b.disabled = true));
    scrapingForm?.querySelectorAll("button").forEach((b) => (b.disabled = true));
    vectorForm?.querySelectorAll("button").forEach((b) => (b.disabled = true));  }

  function setUIProgress(percent, message) {
    if (!progressBox || !bar || !text) return;
    progressBox.style.display = "block";
    bar.style.animation = "none";
    bar.style.width = `${Math.max(0, Math.min(100, percent))}%`;
    text.textContent = message;
  }

  function setUIDone(message) {
    setUIProgress(100, message);
    setTimeout(() => window.location.reload(), 600);
  }

  function setUIFailed(message) {
    if (!progressBox || !text) return;
    progressBox.style.display = "block";
    if (bar) {
      bar.style.animation = "none";
      bar.style.width = "100%";
    }
    text.textContent = message;
    uploadForm?.querySelectorAll("button").forEach((b) => (b.disabled = false));
    scrapingForm?.querySelectorAll("button").forEach((b) => (b.disabled = false));
    vectorForm?.querySelectorAll("button").forEach((b) => (b.disabled = false));
  }

  async function pollVectorJob(jobId) {
    const statusUrl = `/admin/vector-db/status/${jobId}`;

    while (true) {
      const r = await fetch(statusUrl, { headers: { "Accept": "application/json" } });
      if (!r.ok) {
        setUIFailed("No se pudo consultar el estado del job.");
        return;
      }

      const data = await r.json();
      const status = data.status;
      const progress = Number(data.progress ?? 0);
      const currentDoc = data.current_doc;

      if (status === "running" || status === "queued") {
        const msg = currentDoc
          ? `Actualizando base vectorial… (${progress}%) — ${currentDoc}`
          : `Actualizando base vectorial… (${progress}%)`;
        setUIProgress(progress, msg);
        await new Promise((res) => setTimeout(res, 1000));
        continue;
      }

      if (status === "done") {
        sessionStorage.removeItem("vector_job_id");
        setUIDone("Base vectorial actualizada.");
        return;
      }

      if (status === "failed") {
        sessionStorage.removeItem("vector_job_id");
        const err = data.error ? ` Error: ${data.error}` : "";
        setUIFailed(`Falló la actualización de la base vectorial.${err}`);
        return;
      }

      // Estado desconocido
      setUIFailed("Estado de job desconocido.");
      return;
    }
  }

  async function startVectorUpdate(e) {
    e.preventDefault();
    if (!vectorForm) return;

    setUIRunning("Lanzando actualización de base vectorial…");

    const r = await fetch(vectorForm.action, {
      method: "POST",
      headers: { "Accept": "application/json" }
    });

    if (!r.ok) {
      setUIFailed("No se pudo iniciar la actualización.");
      return;
    }

    const data = await r.json();
    if (!data.job_id) {
      setUIFailed("No se recibió job_id.");
      return;
    }

    // Guarda el job para poder recuperarlo si se recarga
    sessionStorage.setItem("vector_job_id", String(data.job_id));

    setUIProgress(0, "Actualizando base vectorial… (0%)");
    pollVectorJob(data.job_id);
  }

  async function pollScrapingJob(jobId) {
    const statusUrl = `/admin/documents/web_scraping/status/${jobId}`;

    while (true) {
      const r = await fetch(statusUrl, { headers: { "Accept": "application/json" } });
      if (!r.ok) {
        setUIFailed("No se pudo consultar el estado del scraping.");
        return;
      }

      const data = await r.json();
      const status = data.status;
      const progress = Number(data.progress ?? 0);
      const msg = data.message || `Web scraping… (${progress}%)`;

      if (status === "running" || status === "queued") {
        setUIProgress(progress, msg);
        await new Promise((res) => setTimeout(res, 1000));
        continue;
      }

      if (status === "done") {
        sessionStorage.removeItem("scraping_job_id");
        setUIDone("Web scraping completado.");
        return;
      }

      if (status === "failed") {
        sessionStorage.removeItem("scraping_job_id");
        const err = data.error ? ` Error: ${data.error}` : "";
        setUIFailed(`Falló el web scraping.${err}`);
        return;
      }

      setUIFailed("Estado de scraping desconocido.");
      return;
    }
  }

  async function startScraping(e) {
    e.preventDefault();
    if (!scrapingForm) return;

    setUIRunning("Lanzando web scraping…");

    const r = await fetch(scrapingForm.action, {
      method: "POST",
      headers: { "Accept": "application/json" }
    });

    if (!r.ok) {
      setUIFailed("No se pudo iniciar el web scraping.");
      return;
    }

    const data = await r.json();
    if (!data.job_id) {
      setUIFailed("No se recibió job_id del scraping.");
      return;
    }

    sessionStorage.setItem("scraping_job_id", String(data.job_id));
    setUIProgress(0, "Web scraping… (0%)");
    pollScrapingJob(data.job_id);
  }

  if (vectorForm) {
    vectorForm.addEventListener("submit", startVectorUpdate);
  }

  // Si había un job activo guardado, reanuda polling
  const savedVectorJobId = sessionStorage.getItem("vector_job_id");
  if (savedVectorJobId) {
    setUIRunning("Reanudando seguimiento de la actualización…");
    pollVectorJob(savedVectorJobId);
  }

  // WEB SCRAPING
  if (scrapingForm) {
    scrapingForm.addEventListener("submit", startScraping);
  }

  const savedScrapingJobId = sessionStorage.getItem("scraping_job_id");
  if (savedScrapingJobId) {
    setUIRunning("Reanudando seguimiento del web scraping…");
    pollScrapingJob(savedScrapingJobId);
  }


});
