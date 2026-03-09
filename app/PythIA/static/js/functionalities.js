/* =========================
   EFECTO LUZ 
   ========================= */

document.addEventListener("mousemove", function (e) {
  const luz = e.target.closest(".luz");
  if (!luz) return;

  const rect = luz.getBoundingClientRect();
  const x = ((e.clientX - rect.left) / rect.width) * 100;
  const y = ((e.clientY - rect.top) / rect.height) * 100;

  luz.style.setProperty("--x", `${x}%`);
  luz.style.setProperty("--y", `${y}%`);
});

