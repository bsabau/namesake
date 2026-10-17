// Copy buttons. `data-copy-target` copies one element; `data-copy-variant` copies the
// version picked in the generic/local toggle.
document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-copy-target], [data-copy-variant]");
  if (!button || !navigator.clipboard) return;
  let id = button.dataset.copyTarget;
  if (button.hasAttribute("data-copy-variant")) {
    const picked = document.querySelector('input[name="variant"]:checked');
    id = `copy-${picked ? picked.value : "generic"}`;
  }
  const target = document.getElementById(id);
  if (!target) return;
  navigator.clipboard.writeText((target.value || target.textContent).trim()).then(() => {
    const label = button.textContent;
    button.textContent = "Copied";
    setTimeout(() => { button.textContent = label; }, 1500);
  });
});
