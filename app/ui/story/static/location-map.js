// Map of the selected shelter location: Leaflet over the basemap the view model names.
// The preset locations come from the page (#map-points, the view model's list);
// picking a location card moves the map there. Right-click (long-press on a phone)
// asks the view model's pick_url (/api/places/at) for the areas around that spot; choosing one makes it
// the typed area, with the spot as the visit's pin; Qloo checks it when an animal is picked.

// The basemap under the map, from the view model's tiles (MapTiles in app/views/): a light
// and a dark tile URL, the attribution, the subdomains, and a fallback. Nothing here names
// a tile server; with the MAP_TILES_KEY setting the URLs are CARTO's, without it
// OpenStreetMap's. The dark URL is used when the browser prefers a dark scheme, and the
// map follows a change of scheme. A keyed basemap that keeps failing (the key refused, a
// quota, an outage) gives way to the fallback after a few tile errors. A map drawn over
// the plain tiles (OpenStreetMap, or the fallback) is marked `tiles-plain`, so the
// stylesheet can quieten them instead.
function addBasemap(map, container, tiles) {
  if (!tiles || !tiles.url) return;
  const dark = matchMedia("(prefers-color-scheme: dark)");
  const hasFallback = Boolean(tiles.fallback_url) && tiles.fallback_url !== tiles.url;
  let layer = null;
  let failed = 0; // consecutive tile errors on the keyed layer
  let fellBack = false;
  const show = () => {
    if (layer) layer.remove();
    failed = 0;
    const plain = fellBack || !tiles.dark_url || tiles.dark_url === tiles.url;
    container.classList.toggle("tiles-plain", plain);
    const url = fellBack ? tiles.fallback_url : dark.matches ? tiles.dark_url || tiles.url : tiles.url;
    layer = L.tileLayer(url, {
      maxZoom: (fellBack ? tiles.fallback_max_zoom : tiles.max_zoom) || 19,
      subdomains: (fellBack ? "" : tiles.subdomains) || "abc",
      attribution: (fellBack ? tiles.fallback_attribution : tiles.attribution) || "",
    }).addTo(map);
    if (hasFallback && !fellBack) {
      // Only a layer that keeps failing gives way: a loaded tile resets the count.
      layer.on("tileload", () => { failed = 0; });
      layer.on("tileerror", () => {
        failed += 1;
        if (failed >= 3) {
          fellBack = true;
          show();
        }
      });
    }
  };
  show();
  dark.addEventListener("change", show);
}

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
  // The typed area has no point of its own until Qloo checks it: stay on the spot the
  // visitor picked, if any, else on the first area.
  const known = checked && points[checked.value] ? checked.value : null;
  const pending = !known && pinLat && pinLat.value
    ? { ...first, label: "the spot you picked", pin: { latitude: Number(pinLat.value), longitude: Number(pinLon.value) } }
    : null;
  const start = pending || points[known || Object.keys(points)[0]];
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

  // The basemap comes from the view model (#map-tiles: CARTO with a key, else OpenStreetMap).
  const tiles = document.getElementById("map-tiles");
  addBasemap(map, container, tiles ? JSON.parse(tiles.textContent) : null);

  // The accent is read from the stylesheet, and again when the colour scheme changes, so
  // the circle and the pins follow the basemap.
  const accentNow = () => getComputedStyle(document.documentElement)
    .getPropertyValue("--accent").trim() || "#227880";
  let accent = accentNow();
  const pinStyle = () => ({ radius: 8, color: "#fff", weight: 2, fillColor: accent, fillOpacity: 1 });

  // A soft circle around the shelter's area, and a pin only where the visitor put one.
  const area = L.circle(centreOf(start), {
    radius: start.shelter_radius_m,
    color: accent,
    weight: 2,
    fillOpacity: 0.15,
  }).addTo(map);
  const pin = L.circleMarker(centreOf(start), pinStyle());
  let picked = null;
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    accent = accentNow();
    area.setStyle({ color: accent });
    pin.setStyle({ fillColor: accent });
    if (picked) picked.setStyle({ fillColor: accent });
  });
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
  const typed = document.getElementById("location-typed");
  if (!pickUrl || !field || !typed || !pinLat || !pinLon) return;

  // Typing a different area drops a spot picked earlier: it belonged to that lookup.
  field.addEventListener("input", (event) => {
    if (event.inputType) pinLat.value = pinLon.value = "";
  });

  map.on("contextmenu", async (event) => {
    const spot = event.latlng.wrap();
    if (picked) picked.remove();
    picked = L.circleMarker(spot, pinStyle()).addTo(map);

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
        // The area becomes the choice; Qloo checks it once an animal is picked.
        typed.checked = true;
        typed.dispatchEvent(new Event("change", { bubbles: true }));
        // After the click: a button taken out of the popup mid-click reads to Leaflet as
        // a click on the map, which would close the popup.
        setTimeout(() => {
          text.textContent = field.dataset.pickedNote || text.textContent;
          box.replaceChildren(text);
          popup.update();
        }, 0);
      });
      box.append(use);
    }
    popup.update(); // fit and pan to the buttons that just arrived
  });
})();
