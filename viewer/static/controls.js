/* Peripheral controls and display backlight follow device SSE snapshots. */
if (typeof document !== 'undefined') (() => {
  const byId = id => document.getElementById(id);
  const error = text => { byId('control-error').textContent = text; };
  const post = async (path, body) => {
    const response = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    if (!response.ok) throw new Error(await response.text());
    return response.json();
  };
  let state = {}, online = false, peripheralBusy = false;
  function render() {
    const busy = !online || peripheralBusy || Boolean(state.transition || state.peripheral_transition);
    if (state.brightness != null) {
      const brightness = Math.max(1, Math.min(40, state.brightness));
      byId('scr').style.filter = `brightness(${.2 + .8 * brightness / 40})`;
    }
    const sd = byId('sd-toggle'), usb = byId('usb-toggle');
    sd.disabled = busy || !state.sd_available;
    usb.disabled = busy;
    sd.classList.toggle('is-ejected', !state.sd_inserted);
    sd.setAttribute('aria-pressed', String(Boolean(state.sd_inserted)));
    const sdLabel = state.sd_inserted ? 'Eject SD card' : 'Insert SD card';
    sd.setAttribute('aria-label', sdLabel); sd.querySelector('.key-label').textContent = sdLabel;
    usb.classList.toggle('is-connected', Boolean(state.usb_connected));
    usb.setAttribute('aria-pressed', String(Boolean(state.usb_connected)));
    const usbLabel = state.usb_connected ? 'Disconnect USB · charging' : 'Connect USB charging cable';
    usb.setAttribute('aria-label', usbLabel); usb.querySelector('.key-label').textContent = usbLabel;
  }
  async function peripheral(body) {
    if (peripheralBusy) return;
    peripheralBusy = true; render();
    try {
      state = await post('/peripheral', body);
      error('');
    } catch (reason) { error(reason.message); }
    finally { peripheralBusy = false; render(); }
  }
  // Ejecting is the destructive direction: it unmounts the card under the player,
  // and during playback it fails outright. Require a second click to confirm.
  const EJECT_CONFIRM_MS = 3000, EJECT_HINT = 'Click the card again to eject';
  let ejectArmedUntil = 0, ejectTimer = null;
  const disarmEject = () => { clearTimeout(ejectTimer); ejectTimer = null; ejectArmedUntil = 0; };
  byId('sd-toggle').onclick = () => {
    if (state.sd_inserted && performance.now() > ejectArmedUntil) {
      disarmEject();
      ejectArmedUntil = performance.now() + EJECT_CONFIRM_MS;
      error(EJECT_HINT);
      // The hint describes a window, so it has to go when the window closes.
      ejectTimer = setTimeout(() => {
        ejectArmedUntil = 0;
        if (byId('control-error').textContent === EJECT_HINT) error('');
      }, EJECT_CONFIRM_MS);
      return;
    }
    disarmEject();
    peripheral({name:'sd', inserted:!state.sd_inserted});
  };
  byId('usb-toggle').onclick = () => peripheral({name:'usb', connected:!state.usb_connected});
  window.viewerControls = {
    update(value) { state = value; online = true; render(); },
    unavailable() { online = false; render(); },
    error
  };
  render();
})();
