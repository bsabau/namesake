// The shelter bar above the animals: it names the chosen area, and its panel holds the
// choice. Kept apart from the map script, so it works even when the map cannot load.

(function () {
  const panel = document.getElementById("shelter");
  const form = document.getElementById("pick");
  const data = document.getElementById("map-points");
  if (!panel || !form) return;
  const name = document.getElementById("shelter-name");
  const region = document.getElementById("shelter-region");
  const points = data ? Object.fromEntries(JSON.parse(data.textContent).map((p) => [p.id, p])) : {};
  // The typed area (decision 32): a choice like the presets, named as typed.
  const typed = document.getElementById("location-typed");
  const field = document.getElementById("custom-location-text");
  const pins = ["pin-lat", "pin-lon"].map((id) => document.getElementById(id)).filter(Boolean);
  const preset = document.querySelector('input[name="location"]:checked');
  if (typed && preset && preset !== typed) typed.dataset.near = preset.value;

  const rename = (label, where) => {
    if (name) name.textContent = label;
    if (region) region.textContent = where;
    panel.classList.toggle("unchosen", !label);
  };

  // Choosing an area renames the bar (label and region come from the view model).
  document.querySelectorAll('input[name="location"]').forEach((input) => {
    input.addEventListener("change", () => {
      if (input === typed) {
        rename(field ? field.value.trim() : "", "");
        return;
      }
      const p = points[input.value];
      if (p) rename(p.label, p.region);
      // A preset: suggestions rank near it, and a spot picked for the typed area is dropped.
      if (typed) typed.dataset.near = input.value;
      pins.forEach((pin) => (pin.value = ""));
    });
  });

  // "Add your own animal" opens its form with a GET: the area goes along, the spot never
  // does, since a GET puts it in the URL.
  form.addEventListener("submit", (event) => {
    if ((event.submitter && event.submitter.getAttribute("formmethod")) !== "get") return;
    pins.forEach((pin) => (pin.disabled = true));
    setTimeout(() => pins.forEach((pin) => (pin.disabled = false)), 0);
  });

  if (typed && field) {
    // Typing an area chooses it.
    field.addEventListener("input", () => {
      typed.checked = true;
      rename(field.value.trim(), "");
    });
    // Enter keeps the area and closes the panel, so the animals are next; it never picks
    // the first animal for the visitor. Picking a suggestion with Enter is the suggestion
    // list's own (it prevents the default first).
    field.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" || event.defaultPrevented) return;
      event.preventDefault();
      if (!field.value.trim()) return;
      typed.checked = true;
      rename(field.value.trim(), "");
      panel.open = false;
    });
  }

  // Picking an animal with no area chosen: the required choice sits in the panel, which a
  // browser cannot point at while it is closed, so open it and ask again.
  form.addEventListener(
    "invalid",
    () => {
      if (panel.open) return;
      panel.open = true;
      setTimeout(() => form.reportValidity(), 0);
    },
    true,
  );
})();
