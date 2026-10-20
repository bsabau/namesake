// Working page: follow the run's server-sent events and show each step as it lands.
// On "done", go to the result. The steps rendered by the server are replaced, since
// the stream replays every step from the start.

(function () {
  const root = document.querySelector('[data-role="working"]');
  if (!root || typeof EventSource === "undefined") return;
  const list = root.querySelector('[data-role="steps"]');
  const status = root.querySelector('[data-role="status"]');
  const source = new EventSource(root.dataset.eventsUrl);
  let first = true;

  // A sign of life between steps: a word that changes every few seconds, and the time
  // since the last step. The words come from the view model (data-words).
  const busy = root.querySelector('[data-role="busy"]');
  // Counted from the server's last step, so a reload does not restart the clock.
  let lastStep = Date.now() - 1000 * (Number(busy && busy.dataset.seconds) || 0);
  // The stream replays the steps already on the page first; only later ones are new.
  const shown = list.children.length;
  let streamed = 0;
  let timers = [];
  const stopBusy = () => {
    timers.forEach(clearInterval);
    timers = [];
    if (busy) busy.remove();
  };
  if (busy) {
    const words = JSON.parse(busy.dataset.words);
    const word = busy.querySelector(".busy-word");
    const time = busy.querySelector(".busy-time");
    let i = 0;
    timers.push(setInterval(() => {
      i = (i + 1) % words.length;
      word.textContent = words[i];
    }, 3000));
    timers.push(setInterval(() => {
      const s = Math.floor((Date.now() - lastStep) / 1000);
      time.textContent = s < 3 ? "" : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")} ${busy.dataset.since}`;
    }, 1000));
  }

  source.addEventListener("step", (event) => {
    streamed += 1;
    if (streamed > shown) lastStep = Date.now();
    if (first) { list.innerHTML = ""; first = false; }
    const step = JSON.parse(event.data);
    const item = document.createElement("li");
    item.className = `step step-${step.kind}`;
    item.textContent = step.text;
    list.appendChild(item);
  });

  source.addEventListener("done", (event) => {
    source.close();
    stopBusy();
    const outcome = JSON.parse(event.data);
    // A typed area Qloo did not pass: the page, rebuilt, shows what Qloo said and its
    // candidates. Once shown, the stream's replay ends here.
    if (outcome.area) {
      if (!document.querySelector('[data-role="area-check"]')) window.location.reload();
      return; // the page's own status says it already
    }
    if (outcome.failed) {
      status.textContent = "The run stopped before it finished. The steps above show where.";
      return;
    }
    status.textContent = "Finished. Opening the result…";
    setTimeout(() => { window.location.href = root.dataset.resultUrl; }, 800);
  });

  source.onerror = () => {
    stopBusy();
    status.textContent = "Lost the connection to the run. Reload to catch up.";
    source.close();
  };
})();
