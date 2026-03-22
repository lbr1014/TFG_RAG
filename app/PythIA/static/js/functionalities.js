/* =========================
   EFECTO LUZ 
   ========================= */

function initLightEffect(selector = ".luz") {
  document.addEventListener("mousemove", function (e) {
    const el = e.target.closest(selector);
    if (!el) return;

    const rect = el.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * 100;
    const y = ((e.clientY - rect.top) / rect.height) * 100;

    el.style.setProperty("--x", `${x}%`);
    el.style.setProperty("--y", `${y}%`);
  });
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

  if (!deleteModal || !deleteName || !confirmBtn) return

  let currentFormId = null

  deleteModal.addEventListener("show.bs.modal", function (event) {

      const button = event.relatedTarget

      const itemName = button.getAttribute("data-item-name")
      const formId = button.getAttribute("data-form-id")

      deleteName.textContent = itemName
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
  if (!body) return;

  const storageKey = "pythia_theme";
  const buttons = document.querySelectorAll(".theme-option");

  function applyTheme(theme) {
    const resolvedTheme = theme === "light" ? "light" : "dark";
    body.setAttribute("data-theme", resolvedTheme);
    localStorage.setItem(storageKey, resolvedTheme);

    buttons.forEach((button) => {
      const isActive = button.dataset.themeValue === resolvedTheme;
      button.classList.toggle("active", isActive);
      button.setAttribute("aria-pressed", isActive ? "true" : "false");
    });
  }

  const savedTheme = localStorage.getItem(storageKey) || body.getAttribute("data-theme") || "dark";
  applyTheme(savedTheme);

  buttons.forEach((button) => {
    button.addEventListener("click", function () {
      applyTheme(button.dataset.themeValue);
    });
  });
}

initLightEffect();

initChunksModal();

initDeleteModal();

initThemeSelector();
