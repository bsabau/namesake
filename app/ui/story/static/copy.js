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
  const label = button.textContent;
  const say = (word) => {
    button.textContent = word;
    setTimeout(() => { button.textContent = label; }, 1500);
  };
  navigator.clipboard.writeText((target.value || target.textContent).trim()).then(
    () => say("Copied"),
    // Refused (no permission, an insecure page): select the text to copy by hand.
    () => {
      const range = document.createRange();
      range.selectNodeContents(target);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      say("Selected: copy it");
    },
  );
});
