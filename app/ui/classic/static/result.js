// Picking another name option updates the local version's name, hook and copy text.
// Everything shown comes from the view model; nothing is worked out here.
document.addEventListener("change", (event) => {
  const input = event.target;
  if (input.name !== "local_name") return;
  const version = document.querySelector(".version-local");
  if (!version) return;
  const name = version.querySelector("h1");
  const hook = version.querySelector(".hook");
  const copy = document.getElementById("copy-local");
  const bio = document.getElementById("bio-text");
  name.textContent = input.value;
  if (hook) hook.textContent = input.dataset.hook;
  if (copy && bio) {
    copy.value = `Meet ${input.value}.\n\n${input.dataset.hook}\n\n${bio.textContent.trim()}`;
  }
});
