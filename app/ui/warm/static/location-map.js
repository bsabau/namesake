// Map of the selected shelter location: Leaflet with OpenStreetMap tiles.
// The preset locations come from the page (#map-points, the view model's list);
// picking a location card moves the map there. Right-click (long-press on a phone)
// asks the view model's pick_url (/api/places/at) for the areas around that spot; choosing one sends its
// name to the location form, with the spot as the visit's pin.

(function () {
  const container = document.getElementById("location-map");
  const data = document.getElementById("map-points");
  if (!container || !data || typeof L === "undefined") return;

  const points = Object.fromEntries(JSON.parse(data.textContent).map((p) => [p.id, p]));
  const checked = document.querySelector('input[name="location"]:checked');
  // After a failed area check nothing is selected: stay on the spot the visitor picked.
  const pinLat = document.getElementById("pin-lat");
  const pinLon = document.getElementById("pin-lon");
  const first = points[Object.keys(points)[0]];
  const pending = !checked && pinLat && pinLat.value
    ? { ...first, label: "the spot you picked", pin: { latitude: Number(pinLat.value), longitude: Number(pinLon.value) } }
    : null;
  const start = pending || points[checked ? checked.value : Object.keys(points)[0]];
  const alert = document.getElementById("location-alert");
  if (alert) alert.scrollIntoView({ block: "center" });
  const note = document.getElementById("map-note");

  // The visitor's pin, when they picked one for this area; else the area's centre.
  const centreOf = (p) => (p.pin ? [p.pin.latitude, p.pin.longitude] : [p.latitude, p.longitude]);
  // Narrow maps (phones) zoom out one step so the area still has some context around it.
  const zoomFor = (p) => p.zoom - (container.clientWidth < 500 ? 1 : 0);

  const map = L.map(container, { scrollWheelZoom: false }).setView(centreOf(start), zoomFor(start));

  // The grid can settle after the map is created; re-measure so no tiles are missing.
  new ResizeObserver(() => map.invalidateSize()).observe(container);

  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);

  const accent = getComputedStyle(document.documentElement)
    .getPropertyValue("--accent").trim() || "#d96a4a";
  const pinStyle = { radius: 8, color: "#fff", weight: 2, fillColor: accent, fillOpacity: 1 };

  // A soft circle around the shelter's area, and a pin only where the visitor put one.
  const area = L.circle(centreOf(start), {
    radius: start.shelter_radius_m,
    color: accent,
    weight: 2,
    fillOpacity: 0.15,
  }).addTo(map);
  const pin = L.circleMarker(centreOf(start), pinStyle);
  // The map sits in the shelter panel (shelter-bar.js keeps the bar's text).
  const panel = document.getElementById("shelter");
  let current = start;
  const show = (p) => {
    current = p;
    area.setLatLng(centreOf(p)).setRadius(p.shelter_radius_m);
    if (p.pin) pin.setLatLng(centreOf(p)).addTo(map);
    else pin.remove();
    if (note) note.textContent = p.map_note;
    container.setAttribute("aria-label", `Map of the area around the shelter in ${p.label}`);
  };
  show(start);

  // Leaflet cannot measure a map inside a closed panel: size it on opening, and centre it
  // the first time it gets a real size, so a later reopening keeps the visitor's view.
  let sized = container.clientWidth > 0;
  if (panel) {
    panel.addEventListener("toggle", () => {
      if (!panel.open) return;
      map.invalidateSize();
      if (!sized) map.setView(centreOf(current), zoomFor(current));
      sized = true;
    });
  }

  document.querySelectorAll('input[name="location"]').forEach((input) => {
    input.addEventListener("change", () => {
      const p = points[input.value];
      if (!p) return;
      show(p);
      if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
        map.setView(centreOf(p), zoomFor(p), { animate: false });
      } else {
        map.flyTo(centreOf(p), zoomFor(p), { duration: 1.2 });
      }
    });
  });

  // The search above the map: move there, so the shelter's spot can be picked.
  document.addEventListener("namesake:fly", (event) => {
    const { latitude, longitude } = event.detail || {};
    if (typeof latitude !== "number" || typeof longitude !== "number") return;
    // A city-sized view, one step out on a narrow map, as for the presets.
    const zoom = 12 - (container.clientWidth < 500 ? 1 : 0);
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      map.setView([latitude, longitude], zoom, { animate: false });
    } else {
      map.flyTo([latitude, longitude], zoom, { duration: 1.2 });
    }
  });

  // Picking the shelter's spot.
  const pickUrl = container.dataset.pickUrl;
  const field = document.getElementById("custom-location-text");
  const form = document.getElementById("custom-location");
  if (!pickUrl || !field || !form || !pinLat || !pinLon) return;

  // Typing a different area drops a spot picked earlier: it belonged to that lookup.
  field.addEventListener("input", (event) => {
    if (event.inputType) pinLat.value = pinLon.value = "";
  });

  let picked = null;
  map.on("contextmenu", async (event) => {
    const spot = event.latlng.wrap();
    if (picked) picked.remove();
    picked = L.circleMarker(spot, pinStyle).addTo(map);

    const box = document.createElement("div");
    box.className = "map-pick";
    const text = document.createElement("p");
    text.textContent = "Looking up the area around this spot…";
    box.append(text);
    const popup = L.popup().setLatLng(spot).setContent(box).openOn(map);

    let areas = [];
    let message = "The lookup did not answer. Type the area instead.";
    try {
      // About 100 m, as the server sends on: the exact spot stays out of URLs and logs.
      const response = await fetch(`${pickUrl}?lat=${spot.lat.toFixed(3)}&lon=${spot.lng.toFixed(3)}`);
      const body = await response.json();
      areas = response.ok ? body.places : [];
      const said = response.ok ? body.message : body.detail;
      if (typeof said === "string") message = said;
    } catch {
      // keep the message above
    }
    if (!areas.length) {
      text.textContent = message;
      return;
    }
    text.textContent = "Shelter here? Pick the area Qloo should look at:";
    for (const area of areas) {
      const use = document.createElement("button");
      use.type = "button";
      use.textContent = area.label;
      use.addEventListener("click", () => {
        field.value = area.label;
        pinLat.value = spot.lat.toFixed(4);
        pinLon.value = spot.lng.toFixed(4);
        form.requestSubmit();
      });
      box.append(use);
    }
    popup.update(); // fit and pan to the buttons that just arrived
  });
})();
