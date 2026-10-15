// "Copy listing": copies the listing text for pasting into shelter software.
document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-copy-target]");
  if (!button) return;
  const target = document.getElementById(button.dataset.copyTarget);
  if (!target || !navigator.clipboard) return;
  navigator.clipboard.writeText((target.value || target.textContent).trim()).then(() => {
    const label = button.textContent;
    button.textContent = "Copied";
    setTimeout(() => { button.textContent = label; }, 1500);
  });
});
