// Keep one owned debugger connection per working Flow tab. Task wakeups and
// native clicks use the same serial lane; a click must not detach an active guard.
(() => {
  const sessions = new Map();
  const lanes = new Map();
  let logger = () => {};

  function log(stage, detail) {
    try { logger(stage, detail)?.catch?.(() => {}); } catch (_) {}
  }

  function serial(tabId, fn) {
    const previous = lanes.get(tabId) || Promise.resolve();
    const promise = previous.catch(() => {}).then(fn);
    const tail = promise.catch(() => {});
    lanes.set(tabId, tail);
    tail.finally(() => { if (lanes.get(tabId) === tail) lanes.delete(tabId); });
    return promise;
  }

  async function acquire(tabId) {
    const existing = sessions.get(tabId);
    if (existing) return existing;
    const tab = await chrome.tabs.get(tabId);
    if (!/^https:\/\/flow\.google\.com\//.test(tab.url || '')) throw Error('NOT_FLOW_TAB');
    const target = { tabId };
    await chrome.debugger.attach(target, '1.3');
    const entry = { target, held: false, configured: false, command: '',
      autoDiscardable: tab.autoDiscardable, attachedAt: Date.now(), lastError: '' };
    sessions.set(tabId, entry);
    log('background_guard_attached', { tab_id: tabId });
    return entry;
  }

  async function configure(entry) {
    try {
      await chrome.debugger.sendCommand(entry.target, 'Emulation.setFocusEmulationEnabled', { enabled: true });
      await chrome.debugger.sendCommand(entry.target, 'Page.setWebLifecycleState', { state: 'active' });
      entry.configured = true;
      entry.lastError = '';
    } catch (error) {
      entry.configured = false;
      entry.lastError = String(error?.message || error);
      log('background_guard_configure_failed', { tab_id: entry.target.tabId, error: entry.lastError });
      throw error;
    }
  }

  async function releaseInside(tabId) {
    const entry = sessions.get(tabId);
    if (!entry) return;
    entry.releasing = true;
    try { await chrome.debugger.sendCommand(entry.target, 'Emulation.setFocusEmulationEnabled', { enabled: false }); } catch (_) {}
    try { await chrome.debugger.detach(entry.target); } catch (_) {}
    if (sessions.get(tabId) === entry) sessions.delete(tabId);
    if (typeof entry.autoDiscardable === 'boolean') {
      try { await chrome.tabs.update(tabId, { autoDiscardable: entry.autoDiscardable }); } catch (_) {}
    }
    log('background_guard_released', { tab_id: tabId, command_id: entry.command });
  }

  async function hold(tabId, command) {
    return serial(tabId, async () => {
      const entry = await acquire(tabId);
      const changed = !entry.held || entry.command !== String(command || '');
      try {
        await configure(entry);
        await chrome.tabs.update(tabId, { autoDiscardable: false });
        entry.held = true;
        entry.command = String(command || '');
        if (changed) log('background_guard_held', { tab_id: tabId, command_id: entry.command, focus_emulated: true });
        return { ok: true, attached: true, focus_emulated: true };
      } catch (error) {
        await releaseInside(tabId);
        throw error;
      }
    });
  }

  async function run(tabId, fn) {
    return serial(tabId, async () => {
      const entry = await acquire(tabId);
      try {
        await configure(entry);
        return await fn(entry.target);
      } finally {
        if (!entry.held || !entry.configured) await releaseInside(tabId);
      }
    });
  }

  function release(tabId) { return serial(tabId, () => releaseInside(tabId)); }

  chrome.debugger.onDetach.addListener((target, reason) => {
    const entry = sessions.get(target.tabId);
    if (!entry) return;
    sessions.delete(target.tabId);
    if (!entry.releasing && typeof entry.autoDiscardable === 'boolean') {
      void chrome.tabs.update(target.tabId, { autoDiscardable: entry.autoDiscardable }).catch(() => {});
    }
    log('background_guard_detached', { tab_id: target.tabId, reason, command_id: entry.command });
  });
  chrome.tabs.onRemoved.addListener(tabId => sessions.delete(tabId));
  chrome.tabs.onUpdated.addListener((tabId, change) => {
    if (change.url && !/^https:\/\/flow\.google\.com\//.test(change.url)) {
      void release(tabId).catch(() => {});
    }
  });

  globalThis.FlowStudioBackground = {
    hold, run, release,
    setLogger(fn) { logger = typeof fn === 'function' ? fn : () => {}; },
    ids() { return [...sessions.keys()]; },
    diagnostics() {
      return [...sessions].map(([tab_id, entry]) => ({ tab_id,
        command_id: entry.command, attached: true, held: entry.held,
        focus_emulated: entry.configured, last_error: entry.lastError,
        attached_at: entry.attachedAt }));
    }
  };
})();
