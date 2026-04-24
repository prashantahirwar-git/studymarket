/* StudyMarket — main.js */

document.addEventListener("DOMContentLoaded", () => {

  // ── Auto-dismiss flash messages ──────────────────────────────────────────
  document.querySelectorAll(".alert").forEach(el => {
    setTimeout(() => {
      el.style.transition = "opacity .5s";
      el.style.opacity = "0";
      setTimeout(() => el.remove(), 500);
    }, 4000);
  });

  // ── File drop zone (#file-drop) — click to open picker only ─────────────
  // Drag-drop and change handling is done by the upload page's own script
  // so it can properly trigger the preview section. We only wire the click
  // here so non-upload pages that use .file-drop still work.
  const dropZone = document.getElementById("file-drop");
  if (dropZone) {
    const fileInput = dropZone.querySelector("input[type=file]");
    const label     = dropZone.querySelector(".file-label");

    // Click the zone → open file picker (only if not on upload page which
    // manages its own listeners via inline script)
    if (!document.getElementById("preview-section")) {
      // Not the upload page — wire basic click + drag
      dropZone.addEventListener("click", () => fileInput && fileInput.click());
      dropZone.addEventListener("dragover", e => {
        e.preventDefault(); dropZone.classList.add("drag-over");
      });
      dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag-over"));
      dropZone.addEventListener("drop", e => {
        e.preventDefault();
        dropZone.classList.remove("drag-over");
        if (e.dataTransfer.files.length && fileInput) {
          const dt = new DataTransfer();
          dt.items.add(e.dataTransfer.files[0]);
          fileInput.files = dt.files;
          fileInput.dispatchEvent(new Event("change", { bubbles: true }));
        }
      });
      fileInput && fileInput.addEventListener("change", () => {
        if (fileInput.files.length && label) {
          label.innerHTML = "<strong>📎 " + fileInput.files[0].name + "</strong>";
        }
      });
    } else {
      // Upload page — only wire the click (drag+change handled inline)
      dropZone.addEventListener("click", () => fileInput && fileInput.click());
    }
  }

  // ── Admin tabs ───────────────────────────────────────────────────────────
  const tabBtns   = document.querySelectorAll(".tab-btn");
  const tabPanels = document.querySelectorAll(".tab-panel");
  tabBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      tabBtns.forEach(b => b.classList.remove("active"));
      tabPanels.forEach(p => p.classList.remove("active"));
      btn.classList.add("active");
      const target = document.getElementById(btn.dataset.tab);
      if (target) target.classList.add("active");
    });
  });
  if (tabBtns.length) tabBtns[0].click();

  // ── Mobile hamburger ─────────────────────────────────────────────────────
  const hamburger = document.querySelector(".hamburger");
  const navLinks  = document.querySelector(".nav-links");
  if (hamburger && navLinks) {
    hamburger.addEventListener("click", () => navLinks.classList.toggle("open"));
  }

  // ── Star rating UI ───────────────────────────────────────────────────────
  const stars = document.querySelectorAll(".star-input");
  stars.forEach((star, idx) => {
    star.addEventListener("mouseover", () => highlight(idx));
    star.addEventListener("mouseout",  () => highlight(getSelected() - 1));
    star.addEventListener("click", () => {
      document.getElementById("rating-value").value = idx + 1;
      highlight(idx);
    });
  });
  function highlight(upTo) {
    stars.forEach((s, i) => {
      s.textContent = i <= upTo ? "★" : "☆";
      s.style.color = i <= upTo ? "#f59e0b" : "#d1d5db";
    });
  }
  function getSelected() {
    const rv = document.getElementById("rating-value");
    return rv ? parseInt(rv.value) || 0 : 0;
  }
  if (stars.length) highlight(getSelected() - 1);

  // ── Payment countdown ────────────────────────────────────────────────────
  const countdown = document.getElementById("payment-countdown");
  if (countdown) {
    let secs = parseInt(countdown.dataset.secs || "30");
    const iv = setInterval(() => {
      secs--;
      countdown.textContent = secs;
      if (secs <= 0) {
        clearInterval(iv);
        countdown.closest(".countdown-msg").textContent = "You can now confirm your payment.";
      }
    }, 1000);
  }

});
