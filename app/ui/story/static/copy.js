// Copy buttons. `data-copy-target` copies one element; `data-copy-variant` copies the
// version picked in the generic/local toggle.
document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-copy-target], [data-copy-variant]");
  if (!button) return;
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
  // Without the clipboard API (an insecure page) or when it refuses (no permission): copy
  // through the textarea itself, shown for the moment it takes, then hidden again.
  const byHand = () => {
    const hidden = target.hidden;
    target.hidden = false;
    target.select();
    let copied = false;
    try { copied = document.execCommand("copy"); } catch (error) { copied = false; }
    target.hidden = hidden;
    say(copied ? "Copied" : "Copy failed: select the text");
  };
  const text = (target.value || target.textContent).trim();
  if (!navigator.clipboard) return byHand();
  navigator.clipboard.writeText(text).then(() => say("Copied"), byHand);
});
