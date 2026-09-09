/*
 * Future Leaders Preparatory Academy — connection guard.
 * Built by Innovative FrancisTech.
 *
 * Classroom Wi-Fi drops mid-entry, so this keeps typed work from disappearing:
 *   1. a banner tells staff when the device is offline;
 *   2. the first submit made while offline is held back instead of wiping the
 *      page (pressing save again always goes through, in case the browser is
 *      wrong about the connection);
 *   3. what was typed is kept on this device and offered back on the next visit.
 *
 * Drafts are stored per signed-in user, expire after 12 hours, and never hold
 * passwords, file uploads, or CSRF tokens.
 */
(function () {
  'use strict';

  var DRAFT_PREFIX = 'flpa.draft.';
  var DRAFT_TTL_MS = 12 * 60 * 60 * 1000;
  var SAVE_DEBOUNCE_MS = 700;

  function meta(name) {
    var tag = document.querySelector('meta[name="' + name + '"]');
    return (tag && tag.getAttribute('content')) || '';
  }

  var userKey = meta('flpa-user-key') || 'guest';

  function store() {
    try {
      var probe = '__flpa_probe__';
      window.localStorage.setItem(probe, '1');
      window.localStorage.removeItem(probe);
      return window.localStorage;
    } catch (err) {
      return null; // Private mode or storage disabled: banner still works.
    }
  }

  var storage = store();

  /* ---------------------------------------------------------------- banner */

  var banner = document.createElement('div');
  banner.className = 'flpa-net-banner';
  banner.setAttribute('role', 'status');
  banner.setAttribute('aria-live', 'polite');
  document.addEventListener('DOMContentLoaded', function () {
    document.body.appendChild(banner);
    if (!navigator.onLine) showBanner('offline');
  });

  var bannerTimer = null;
  function showBanner(state, message) {
    clearTimeout(bannerTimer);
    banner.classList.remove('is-offline', 'is-online', 'is-visible');
    banner.classList.add(state === 'offline' ? 'is-offline' : 'is-online');
    banner.textContent =
      message ||
      (state === 'offline'
        ? 'No internet connection. Keep working — your entries are saved on this device.'
        : 'Back online. You can save your work now.');
    // Force the transition to restart when the state flips quickly.
    void banner.offsetWidth;
    banner.classList.add('is-visible');
    if (state !== 'offline') {
      bannerTimer = setTimeout(function () {
        banner.classList.remove('is-visible');
      }, 4000);
    }
  }

  window.addEventListener('offline', function () {
    showBanner('offline');
  });
  window.addEventListener('online', function () {
    showBanner('online');
  });

  /* ---------------------------------------------------------------- drafts */

  function isSavableField(field) {
    if (!field.name || field.disabled) return false;
    if (field.type === 'password' || field.type === 'file' || field.type === 'hidden') return false;
    if (field.name === 'csrf_token') return false;
    return !field.hasAttribute('data-no-draft');
  }

  function formKey(form, index) {
    var id = form.getAttribute('id') || form.getAttribute('action') || 'form-' + index;
    return DRAFT_PREFIX + userKey + '|' + location.pathname + '|' + id;
  }

  function readForm(form) {
    var values = {};
    Array.prototype.forEach.call(form.elements, function (field) {
      if (!isSavableField(field)) return;
      if (field.type === 'checkbox' || field.type === 'radio') {
        if (field.checked) values[field.name + '::' + field.value] = true;
      } else if (field.value) {
        values[field.name] = field.value;
      }
    });
    return values;
  }

  function applyDraft(form, values) {
    Array.prototype.forEach.call(form.elements, function (field) {
      if (!isSavableField(field)) return;
      if (field.type === 'checkbox' || field.type === 'radio') {
        if (values[field.name + '::' + field.value]) field.checked = true;
      } else if (Object.prototype.hasOwnProperty.call(values, field.name)) {
        field.value = values[field.name];
      }
    });
  }

  function saveDraft(form, key, heldOffline) {
    if (!storage) return;
    var values = readForm(form);
    if (!Object.keys(values).length) {
      storage.removeItem(key);
      return;
    }
    try {
      storage.setItem(
        key,
        JSON.stringify({ at: Date.now(), held: !!heldOffline, values: values })
      );
    } catch (err) {
      /* Quota full: losing a draft is better than breaking the page. */
    }
  }

  function loadDraft(key) {
    if (!storage) return null;
    var raw = storage.getItem(key);
    if (!raw) return null;
    try {
      var draft = JSON.parse(raw);
      if (!draft || Date.now() - draft.at > DRAFT_TTL_MS) {
        storage.removeItem(key);
        return null;
      }
      return draft;
    } catch (err) {
      storage.removeItem(key);
      return null;
    }
  }

  function purgeExpiredDrafts() {
    if (!storage) return;
    for (var i = storage.length - 1; i >= 0; i -= 1) {
      var key = storage.key(i);
      if (!key || key.indexOf(DRAFT_PREFIX) !== 0) continue;
      loadDraft(key); // Drops anything past its 12-hour life.
    }
  }

  function offerRestore(form, draft, key) {
    var bar = document.createElement('div');
    bar.className = 'flpa-draft-bar';
    var when = new Date(draft.at).toLocaleString();

    var text = document.createElement('span');
    text.textContent = 'Unsent work from ' + when + ' was saved on this device.';

    var restore = document.createElement('button');
    restore.type = 'button';
    restore.className = 'flpa-draft-restore';
    restore.textContent = 'Restore it';
    restore.addEventListener('click', function () {
      applyDraft(form, draft.values);
      bar.remove();
    });

    var discard = document.createElement('button');
    discard.type = 'button';
    discard.className = 'flpa-draft-discard';
    discard.textContent = 'Discard';
    discard.addEventListener('click', function () {
      if (storage) storage.removeItem(key);
      bar.remove();
    });

    bar.appendChild(text);
    bar.appendChild(restore);
    bar.appendChild(discard);
    form.insertBefore(bar, form.firstChild);
  }

  function watchForm(form, index) {
    var method = (form.getAttribute('method') || 'get').toLowerCase();
    if (method !== 'post') return; // Search/filter forms are not worth keeping.
    if (form.hasAttribute('data-no-draft')) return;
    if (form.querySelector('input[type="password"]')) return; // Login screens.

    var key = formKey(form, index);
    var held = loadDraft(key);
    if (held && held.held) offerRestore(form, held, key);

    var timer = null;
    form.addEventListener('input', function () {
      clearTimeout(timer);
      timer = setTimeout(function () {
        saveDraft(form, key, !navigator.onLine);
      }, SAVE_DEBOUNCE_MS);
    });

    var blockedOnce = false;
    form.addEventListener('submit', function (event) {
      if (navigator.onLine) {
        if (storage) storage.removeItem(key);
        return;
      }
      // Some desktops report "offline" wrongly, so only the first attempt is
      // held back; pressing save again always reaches the server.
      if (blockedOnce) {
        saveDraft(form, key, true);
        return;
      }
      blockedOnce = true;
      event.preventDefault();
      saveDraft(form, key, true);
      showBanner(
        'offline',
        'No connection — your entries are saved on this device. Reconnect and press save again, ' +
          'or press save once more to try anyway.'
      );
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    purgeExpiredDrafts();
    Array.prototype.forEach.call(document.forms, watchForm);

    // A shared device should not keep one teacher's draft for the next user.
    var logout = document.querySelector('a[href$="/logout"]');
    if (logout && storage) {
      logout.addEventListener('click', function () {
        for (var i = storage.length - 1; i >= 0; i -= 1) {
          var key = storage.key(i);
          if (key && key.indexOf(DRAFT_PREFIX + userKey + '|') === 0) storage.removeItem(key);
        }
      });
    }
  });
})();
