/* =========================
   EFECTO LUZ 
   ========================= */

function initLightEffect(selector = ".luz") {
  function updateEffectFromPoint(clientX, clientY) {
    const target = document.elementFromPoint(clientX, clientY);
    const el = target?.closest?.(selector);
    if (!el) return;

    const rect = el.getBoundingClientRect();
    const x = ((clientX - rect.left) / rect.width) * 100;
    const y = ((clientY - rect.top) / rect.height) * 100;

    el.style.setProperty("--x", `${x}%`);
    el.style.setProperty("--y", `${y}%`);
  }

  document.addEventListener("mousemove", function (e) {
    const el = e.target.closest(selector);
    if (!el) return;

    const rect = el.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * 100;
    const y = ((e.clientY - rect.top) / rect.height) * 100;

    el.style.setProperty("--x", `${x}%`);
    el.style.setProperty("--y", `${y}%`);
  });

  document.addEventListener("touchstart", function (e) {
    const touch = e.touches?.[0];
    if (!touch) return;
    updateEffectFromPoint(touch.clientX, touch.clientY);
  }, { passive: true });

  document.addEventListener("touchmove", function (e) {
    const touch = e.touches?.[0];
    if (!touch) return;
    updateEffectFromPoint(touch.clientX, touch.clientY);
  }, { passive: true });
}

/* =========================
   MODAL CHUNKS
   ========================= */

function initChunksModal() {

  const chunksModal = document.getElementById("chunksModal");
  if (!chunksModal) return;  

  chunksModal.addEventListener("show.bs.modal", function (event) {

    const button = event.relatedTarget;
    const consultaId = button?.getAttribute("data-consulta-id");

    const tpl = document.getElementById(`chunks-content-${consultaId}`);
    const body = document.getElementById("chunks-modal-body");

    if (!tpl || !body) return;

    body.innerHTML = tpl.innerHTML;
  });

  chunksModal.addEventListener("hidden.bs.modal", function () {

    const body = document.getElementById("chunks-modal-body");
    if (body) body.innerHTML = "";

  });

}

/* =========================
   BORRADO
   ========================= */

function initDeleteModal(modalId = "deleteConfirmModal") {

  const deleteModal = document.getElementById("deleteConfirmModal")
  const deleteName = document.getElementById("deleteItemName")
  const confirmBtn = document.getElementById("confirmDeleteBtn")
  const deleteQuestion = deleteModal?.querySelector(".delete-modal-question")

  if (!deleteModal || !deleteName || !confirmBtn) return

  let currentFormId = null

  deleteModal.addEventListener("show.bs.modal", function (event) {

      const button = event.relatedTarget

      const itemName = button.getAttribute("data-item-name")
      const formId = button.getAttribute("data-form-id")

      deleteName.textContent = itemName
      if (deleteQuestion) {
          const template = deleteQuestion.dataset.deleteTemplate || "{item}"
          deleteQuestion.firstChild.textContent = template.replace("__ITEM__", "").trim().replace(/\s+\?$/, " ")
      }
      currentFormId = formId

  })

  confirmBtn.addEventListener("click", function () {
      if (currentFormId) {
          document.getElementById(currentFormId).submit()
      }
  })
}

function initThemeSelector() {
  const body = document.body;
  const root = document.documentElement;
  if (!body) return;

  const storageKey = "pythia_theme";
  const buttons = document.querySelectorAll(".theme-option");
  const mediaQuery = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

  function getSystemTheme() {
    return mediaQuery?.matches ? "dark" : "light";
  }

  function applyTheme(theme) {
    const resolvedTheme = theme === "light" ? "light" : "dark";
    body.setAttribute("data-theme", resolvedTheme);
    root.setAttribute("data-bs-theme", resolvedTheme);

    buttons.forEach((button) => {
      const isActive = button.dataset.themeValue === resolvedTheme;
      button.classList.toggle("active", isActive);
      button.setAttribute("aria-pressed", isActive ? "true" : "false");
    });
  }

  const savedTheme = localStorage.getItem(storageKey);
  const initialTheme = savedTheme || getSystemTheme() || body.getAttribute("data-theme") || "dark";
  applyTheme(initialTheme);

  buttons.forEach((button) => {
    button.addEventListener("click", function () {
      const resolvedTheme = button.dataset.themeValue === "light" ? "light" : "dark";
      localStorage.setItem(storageKey, resolvedTheme);
      applyTheme(resolvedTheme);
    });
  });

  mediaQuery?.addEventListener?.("change", function (event) {
    if (localStorage.getItem(storageKey)) return;
    applyTheme(event.matches ? "dark" : "light");
  });
}

initLightEffect();

initChunksModal();

initDeleteModal();

initThemeSelector();
