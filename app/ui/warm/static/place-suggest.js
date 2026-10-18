// Suggestions for a place field: area names from the view model's suggestions_url
// (/api/places), ranked near the area selected on the map, in a list under the field.
// Arrow keys move, Enter picks, Escape closes. If the lookup fails, typing works as
// before. Two fields use it: the typed shelter area (picking fills the field) and the
// search on the map (picking moves the map there, with a "namesake:fly" event).

// The selected area's centre, from the map's data, so nearby places come first.
function nearSelected() {
  const data = document.getElementById("map-points");
  const checked = document.querySelector('input[name="location"]:checked');
  if (!data || !checked) return "";
  const p = JSON.parse(data.textContent).find((x) => x.id === checked.value);
  return p ? `&lat=${p.latitude.toFixed(1)}&lon=${p.longitude.toFixed(1)}` : "";
}

function attachSuggestions(field, list, onChoose, near = nearSelected) {
  if (!field || !list || !field.dataset.suggestUrl) return;

  let timer = null;
  let asked = "";
  let answer = { text: "", places: [] }; // the last answer, with the text it answered
  let active = -1;

  const items = () => [...list.querySelectorAll("li")];
  const close = () => {
    list.hidden = true;
    field.setAttribute("aria-expanded", "false");
    field.removeAttribute("aria-activedescendant");
    active = -1;
  };
  const highlight = (step) => {
    const all = items();
    // From no highlight, Down goes to the first row and Up to the last.
    active = active < 0 ? (step > 0 ? 0 : all.length - 1) : (active + step + all.length) % all.length;
    all.forEach((li, n) => li.setAttribute("aria-selected", String(n === active)));
    field.setAttribute("aria-activedescendant", all[active].id);
  };
  let shown = [];
  const choose = (place) => {
    field.value = place.label;
    asked = place.label;
    answer = { text: "", places: [] };
    close();
    field.focus();
    onChoose(place);
  };

  const show = (places) => {
    shown = places;
    list.replaceChildren(
      ...places.map((p, n) => {
        const li = document.createElement("li");
        li.id = `${list.id}-${n}`;
        li.setAttribute("role", "option");
        li.textContent = p.label;
        // mousedown, not click: it lands before the field loses focus.
        li.addEventListener("mousedown", (event) => {
          event.preventDefault();
          choose(p);
        });
        return li;
      }),
    );
    list.hidden = !places.length;
    field.setAttribute("aria-expanded", String(places.length > 0));
    active = -1;
  };

  field.addEventListener("input", () => {
    clearTimeout(timer);
    const text = field.value.trim();
    // Back to the text last answered (a typo undone): show that answer again.
    if (text === answer.text && text.length >= 3) return show(answer.places);
    // Suggestions for other text must not be pickable while new ones are fetched.
    close();
    if (text.length < 3 || text === asked) return; // the same text is already being asked
    timer = setTimeout(async () => {
      asked = text;
      try {
        // The area's centre to one decimal (about 11 km): enough to rank nearby places.
        const response = await fetch(`${field.dataset.suggestUrl}?q=${encodeURIComponent(text)}${near()}`);
        if (text !== asked) return; // superseded by a later lookup, which owns the list
        if (!response.ok) return close();
        const body = await response.json();
        if (text !== asked) return;
        answer = { text, places: body.places };
        if (field.value.trim() === text) show(answer.places);
      } catch {
        // No suggestions this time; the field still takes what is typed.
        if (text === asked) close();
      }
    }, 300);
  });

  field.addEventListener("keydown", (event) => {
    if (list.hidden) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      highlight(event.key === "ArrowDown" ? 1 : -1);
    } else if (event.key === "Enter" && active >= 0) {
      event.preventDefault(); // pick the suggestion; a second Enter submits
      choose(shown[active]);
    } else if (event.key === "Escape") {
      close();
    }
  });
  field.addEventListener("blur", close);
}

attachSuggestions(
  document.getElementById("custom-location-text"),
  document.getElementById("place-suggestions"),
  () => {},
);

// The search on the map only moves it; it never chooses an area or asks Qloo. Enter in
// it never submits the form around it.
(function () {
  const search = document.getElementById("map-search-text");
  if (!search) return;
  search.addEventListener("keydown", (event) => {
    if (event.key === "Enter") event.preventDefault();
  });
  // Unbiased: the search is for going somewhere else, not near the area selected.
  attachSuggestions(
    search,
    document.getElementById("map-search-suggestions"),
    (place) => document.dispatchEvent(new CustomEvent("namesake:fly", { detail: place })),
    () => "",
  );
})();
