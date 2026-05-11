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
   MODAL RESPUESTA HISTORIAL
   ========================= */

function initHistoryAnswerModal() {
  const answerModal = document.getElementById("answerModal")
  if (!answerModal) return

  const answerModalInstance = window.bootstrap
    ? window.bootstrap.Modal.getOrCreateInstance(answerModal)
    : null

  function renderAnswerFromCard(card) {
    const consultaId = card?.getAttribute("data-consulta-id")
    const question = card?.getAttribute("data-question") || ""
    const source = document.getElementById(`answer-content-${consultaId}`)
    const body = document.getElementById("answer-modal-body")
    const questionNode = document.getElementById("answer-modal-question")

    if (questionNode) questionNode.textContent = question
    if (!source || !body) return

    let answer = ""
    try {
      answer = JSON.parse(source.textContent || "\"\"")
    } catch {
      answer = source.textContent || ""
    }

    if (window.pythiaRenderMarkdown) {
      window.pythiaRenderMarkdown(body, answer)
    } else {
      body.textContent = answer
    }
  }

  document.querySelectorAll(".history-card-answer-trigger").forEach((trigger) => {
    trigger.addEventListener("click", function () {
      renderAnswerFromCard(trigger)
      answerModalInstance?.show()
    })
  })

  answerModal.addEventListener("hidden.bs.modal", function () {
    const body = document.getElementById("answer-modal-body")
    const questionNode = document.getElementById("answer-modal-question")
    if (body) body.innerHTML = ""
    if (questionNode) questionNode.textContent = ""
  })
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
  let submitName = null
  let submitValue = null

  deleteModal.addEventListener("show.bs.modal", function (event) {

      const button = event.relatedTarget

      const itemName = button.getAttribute("data-item-name")
      const formId = button.getAttribute("data-form-id")
      submitName = button.getAttribute("data-submit-name")
      submitValue = button.getAttribute("data-submit-value")

      deleteName.textContent = itemName
      if (deleteQuestion) {
          const template = deleteQuestion.dataset.deleteTemplate || "{item}"
          deleteQuestion.firstChild.textContent = template.replace("__ITEM__", "").trim().replace(/\s+\?$/, " ")
      }
      currentFormId = formId

  })

  confirmBtn.addEventListener("click", function () {
      if (currentFormId) {
          const form = document.getElementById(currentFormId)
          if (form && submitName && submitValue) {
              const input = document.createElement("input")
              input.type = "hidden"
              input.name = submitName
              input.value = submitValue
              form.appendChild(input)
          }
          form?.submit()
      }
  })
}

function initAdminUserSelection() {
  const selectAll = document.getElementById("select-all-users")
  const checkboxes = document.querySelectorAll(".user-row-checkbox")
  const bulkButtons = document.querySelectorAll(".admin-users-bulk-button")
  if (!selectAll || !checkboxes.length) return

  function updateBulkState() {
    const checkedCount = document.querySelectorAll(".user-row-checkbox:checked").length
    selectAll.checked = checkedCount === checkboxes.length
    selectAll.indeterminate = checkedCount > 0 && checkedCount < checkboxes.length
    bulkButtons.forEach((button) => {
      button.disabled = checkedCount === 0
    })
  }

  selectAll.addEventListener("change", function () {
    checkboxes.forEach((checkbox) => {
      checkbox.checked = selectAll.checked
    })
    updateBulkState()
  })

  checkboxes.forEach((checkbox) => {
    checkbox.addEventListener("change", updateBulkState)
  })

  updateBulkState()
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

function initBootstrapTooltips() {
  if (!window.bootstrap?.Tooltip) return

  document.querySelectorAll('[data-bs-toggle="tooltip"], [data-bs-tooltip="tooltip"]').forEach((element) => {
    window.bootstrap.Tooltip.getOrCreateInstance(element)
  })
}

function initProfileImagePreview() {
  const input = document.querySelector("[data-preview-target]")
  if (!input) return

  const preview = document.getElementById(input.dataset.previewTarget)
  if (!preview) return

  input.addEventListener("change", function () {
    const file = input.files?.[0]
    if (!file) return

    const reader = new FileReader()
    reader.addEventListener("load", function () {
      preview.innerHTML = ""
      const image = document.createElement("img")
      image.src = reader.result
      image.alt = input.labels?.[0]?.textContent || "Perfil"
      preview.appendChild(image)
    })
    reader.readAsDataURL(file)
  })
}

initLightEffect();

initChunksModal();

initHistoryAnswerModal();

initDeleteModal();

initAdminUserSelection();

initThemeSelector();

initBootstrapTooltips();

initProfileImagePreview();
