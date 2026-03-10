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

initLightEffect();

initChunksModal();