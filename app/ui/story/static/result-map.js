// Result map: the shelter's area plus Qloo map cells coloured by lift, over the basemap
// the view model names (addBasemap below).
// Everything drawn comes from the view model in #map-data; no data is computed here.

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
  let failed = 0;
  let fellBack = false;
  const show = () => {
    if (layer) layer.remove();
    const plain = fellBack || !tiles.dark_url || tiles.dark_url === tiles.url;
    container.classList.toggle("tiles-plain", plain);
    const url = fellBack ? tiles.fallback_url : dark.matches ? tiles.dark_url || tiles.url : tiles.url;
    layer = L.tileLayer(url, {
      maxZoom: (fellBack ? tiles.fallback_max_zoom : tiles.max_zoom) || 19,
      subdomains: (fellBack ? "" : tiles.subdomains) || "abc",
      attribution: (fellBack ? tiles.fallback_attribution : tiles.attribution) || "",
    }).addTo(map);
    if (hasFallback && !fellBack) {
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
  const container = document.getElementById("result-map");
  const data = document.getElementById("map-data");
  if (!container || !data || typeof L === "undefined") return;

  const view = JSON.parse(data.textContent);
  const map = L.map(container, { scrollWheelZoom: false })
    .setView([view.latitude, view.longitude], view.zoom);

  // The grid can settle after the map is created; re-measure so no tiles are missing.
  new ResizeObserver(() => map.invalidateSize()).observe(container);

  // The basemap comes from the view model (CARTO with a key, else OpenStreetMap).
  addBasemap(map, container, view.tiles);

  // The palette is read from the stylesheet, and read again when the colour scheme
  // changes, so the cells and the shelter's circle follow the basemap.
  const palette = () => {
    const css = getComputedStyle(document.documentElement);
    const colour = (name, fallback) => css.getPropertyValue(name).trim() || fallback;
    return {
      warm: colour("--lift-up", "#d96a4a"),
      cool: colour("--lift-down", "#3b8ea5"),
      none: colour("--lift-none", "#8a7f75"),
      accent: colour("--accent", "#d96a4a"),
    };
  };
  let colours = palette();

  // The shelter's area: around the spot the visitor picked, when they picked one.
  const shelter = view.pin ? [view.pin.latitude, view.pin.longitude] : [view.latitude, view.longitude];
  const area = L.circle(shelter, {
    radius: view.shelter_radius_m,
    color: colours.accent,
    weight: 2,
    dashArray: "4 4",
    fill: false,
  }).addTo(map);
  let pin = null;
  if (view.pin) {
    pin = L.circleMarker(shelter, {
      radius: 8, color: "#fff", weight: 2, fillColor: colours.accent, fillOpacity: 1,
    }).bindTooltip("The spot you picked for the shelter").addTo(map);
  }

  const fillFor = (cell) => {
    const { warm, cool, none } = colours;
    return cell.lift === null ? none : cell.lift > 0 ? warm : cool;
  };
  const cells = view.cells.map((cell) => {
    // A compared cell never draws paler than a grey one, so warm cells are easy to count.
    const strength = cell.lift === null ? 0.25 : 0.3 + 0.5 * Math.min(1, Math.abs(cell.lift));
    const fill = fillFor(cell);
    const rect = L.rectangle(
      [[cell.south, cell.west], [cell.north, cell.east]],
      { color: fill, weight: 1, fillColor: fill, fillOpacity: strength },
    ).bindTooltip(cell.label).addTo(map);
    return { cell, rect };
  });
  const layers = cells.map((c) => c.rect);

  // A change of scheme recolours what was drawn; the venue pins are styled by the sheet.
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    colours = palette();
    area.setStyle({ color: colours.accent });
    if (pin) pin.setStyle({ fillColor: colours.accent });
    for (const { cell, rect } of cells) {
      const fill = fillFor(cell);
      rect.setStyle({ color: fill, fillColor: fill });
    }
  });

  // The suggested places, numbered as in the list beside the map (decision 4, revised).
  for (const venue of view.venues || []) {
    const icon = L.divIcon({
      className: "venue-pin",
      html: `<span>${venue.number}</span>`,
      iconSize: [24, 24],
      iconAnchor: [12, 12],
    });
    const label = document.createElement("span");
    label.textContent = `${venue.number}. ${venue.name}`; // text, never markup
    const marker = L.marker([venue.latitude, venue.longitude], { icon, keyboard: false })
      .bindTooltip(label)
      .addTo(map);
    // The map frames the cells and the near pins; a far pin is drawn but not framed.
    if (venue.in_view) layers.push(marker);
  }

  // A short key on the map itself (the view model's note); the caption says the rest.
  let keyBox = null;
  if (view.note) {
    const key = L.control({ position: "bottomleft" });
    key.onAdd = () => {
      const box = (keyBox = L.DomUtil.create("div", "map-key"));
      const heading = L.DomUtil.create("strong", "", box);
      heading.textContent = view.note_heading;
      const text = L.DomUtil.create("p", "", box);
      text.textContent = view.note;
      L.DomEvent.disableClickPropagation(box);
      return box;
    };
    key.addTo(map);
  }

  // The cells, and the visitor's pin with them, so it is never off the edge.
  if (view.pin) layers.push(L.circleMarker(shelter, { radius: 0, opacity: 0 }));
  if (layers.length) {
    const group = L.featureGroup(layers);
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    // Framed above the key, so no cell or pin sits under it.
    const below = keyBox ? Math.min(keyBox.offsetHeight + 10, map.getSize().y * 0.4) : 0;
    map.fitBounds(group.getBounds().pad(0.15), {
      maxZoom: view.zoom + 1,
      paddingTopLeft: [10, 10],
      paddingBottomRight: [10, below],
      animate: !still,
    });
  }
})();
