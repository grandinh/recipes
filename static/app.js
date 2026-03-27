/**
 * Recipe Manager — client-side JS
 * Handles: import form, cooking mode, recipe scaling, nutrition rows, quick rate,
 *          calendar, grocery checkbox delegation, cooking timers, step navigation.
 * All inline scripts have been moved here for CSP compliance.
 *
 * All init functions are idempotent (safe to call multiple times) so they
 * can re-run after HTMX swaps and hx-boost navigation without duplicating
 * event listeners.
 *
 * Convention: all new code uses var/function (ES5 style) to match existing patterns.
 */

// ---------------------------------------------------------------------------
// Module-level state
// ---------------------------------------------------------------------------
var _cookingState = { active: false, recipeId: null, wakeLock: null };
var _timerIntervalId = null;
var _timers = [];
var _audioCtx = null;
var _isBeeping = false;

document.addEventListener('DOMContentLoaded', function () {
  initAll();
  initHtmxHandlers();
  initDocumentDelegation();
  _hydrateTimers();
});

function initAll() {
  initImportForm();
  initPaprikaImportForm();
  initCookingMode();
  initScaling();
  initNutritionRows();
  initQuickRate();
  initCalendar();
  initTimerTriggers();
  initGroceryFilter();
}

// --- HTMX lifecycle handlers ---
function initHtmxHandlers() {
  // Re-init after HTMX swaps (partial updates and hx-boost navigation)
  document.body.addEventListener('htmx:afterSettle', function (evt) {
    var target = evt.detail.target;
    // Boosted navigation replaces <main> content — re-init everything
    if (target.tagName === 'MAIN' || target.closest('main')) {
      // Ghost cooking mode fix: detect recipe change
      var newBtn = document.getElementById('cookingModeBtn');
      var newRecipeId = newBtn ? newBtn.dataset.recipeId : null;
      if (_cookingState.active && newRecipeId !== _cookingState.recipeId) {
        _cookingState.active = false;
        _cookingState.recipeId = null;
        document.body.classList.remove('cooking-mode');
      }
      initAll();
      return;
    }
    // Calendar grid swap — re-init calendar
    if (target.id === 'calendar-grid' || target.querySelector('#calendar-grid')) {
      initCalendar();
    }
    // Targeted swaps — only re-init affected widgets
    if (target.querySelector('#scaleButtons') || target.id === 'scaleButtons' ||
        target.classList.contains('scaling-section')) {
      initScaling();
      _restoreCookingState();
      _restoreStepState();
    }
    // Re-init timer triggers after recipe content swap
    initTimerTriggers();
    // Re-init grocery filter after items list swap
    if (target.id === 'items-list' || target.querySelector('#items-list')) {
      initGroceryFilter();
    }
    // Per-item grocery swap — update remaining count (race condition fix)
    if (target.classList && target.classList.contains('grocery-item')) {
      _updateGroceryRemaining();
      _updateAisleEmptyState();
    }
    // Calendar grid swap — clear stale form fields (race condition fix)
    if (target.id === 'calendar-grid' || target.querySelector('#calendar-grid')) {
      _clearCalendarForm();
    }
  });

  // Browser back/forward with hx-push-url — re-init after history restoration
  document.body.addEventListener('htmx:historyRestore', function () {
    initAll();
  });
}

// --- Document-level delegation (bound once, survives all navigation) ---
function initDocumentDelegation() {
  // Grocery checkbox delegation (replaces inline onchange for CSP)
  if (!initDocumentDelegation._groceryBound) {
    initDocumentDelegation._groceryBound = true;
    document.addEventListener('change', function (e) {
      var checkbox = e.target;
      if (checkbox.type !== 'checkbox') return;
      var form = checkbox.closest('form');
      if (!form) return;
      if (form.closest('.grocery-item') || form.closest('.filter-row')) {
        form.requestSubmit();
      }
    });
  }

  // Auto-submit selects (replaces onchange for CSP — pantry matches)
  if (!initDocumentDelegation._selectBound) {
    initDocumentDelegation._selectBound = true;
    document.addEventListener('change', function (e) {
      var select = e.target;
      if (select.tagName !== 'SELECT') return;
      var form = select.closest('form');
      if (!form) return;
      if (form.closest('.filter-row')) {
        form.submit();
      }
    });
  }

  // Ingredient click — event delegation for cooking mode
  if (!initDocumentDelegation._ingredientBound) {
    initDocumentDelegation._ingredientBound = true;
    document.addEventListener('click', function (e) {
      var li = e.target.closest('.ingredient-item');
      if (!li || !_cookingState.active) return;
      li.classList.toggle('strikethrough');
      var key = 'cooking-' + _cookingState.recipeId + '-ingredient-' + li.dataset.index;
      if (li.classList.contains('strikethrough')) {
        localStorage.setItem(key, '1');
      } else {
        localStorage.removeItem(key);
      }
    });

    // Sync across tabs
    window.addEventListener('storage', function (e) {
      if (!e.key || !_cookingState.recipeId ||
          !e.key.startsWith('cooking-' + _cookingState.recipeId)) return;
      var idx = e.key.split('-ingredient-')[1];
      var li = document.querySelector(
        '.ingredient-item[data-index="' + idx + '"]'
      );
      if (li) {
        if (e.newValue === '1') {
          li.classList.add('strikethrough');
        } else {
          li.classList.remove('strikethrough');
        }
      }
    });
  }

  // Step navigation — click delegation
  if (!initDocumentDelegation._stepClickBound) {
    initDocumentDelegation._stepClickBound = true;
    document.addEventListener('click', function (e) {
      if (!_cookingState.active) return;
      var step = e.target.closest('.direction-step');
      if (!step) return;
      // Don't change step if clicking a timer button
      if (e.target.closest('.timer-trigger-btn')) return;
      _setActiveStep(step);
    });
  }

  // Step navigation — keyboard
  if (!initDocumentDelegation._stepKeyBound) {
    initDocumentDelegation._stepKeyBound = true;
    document.addEventListener('keydown', function (e) {
      if (!_cookingState.active) return;
      var steps = document.querySelectorAll('.direction-step');
      if (!steps.length) return;

      var currentIdx = -1;
      for (var i = 0; i < steps.length; i++) {
        if (steps[i].classList.contains('active-step')) {
          currentIdx = i;
          break;
        }
      }

      if (e.key === 'ArrowDown' || e.key === ' ') {
        e.preventDefault();
        if (currentIdx < steps.length - 1) {
          _setActiveStep(steps[currentIdx + 1]);
        }
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (currentIdx > 0) {
          _setActiveStep(steps[currentIdx - 1]);
        }
      }
    });
  }

  // Timer panel toggle
  if (!initDocumentDelegation._timerToggleBound) {
    initDocumentDelegation._timerToggleBound = true;
    document.addEventListener('click', function (e) {
      var toggle = e.target.closest('.timer-panel-toggle');
      if (!toggle) return;
      var panel = document.getElementById('timer-panel');
      if (!panel) return;
      panel.classList.toggle('expanded');
      toggle.setAttribute('aria-expanded',
        panel.classList.contains('expanded') ? 'true' : 'false');
    });

    // Timer dismiss
    document.addEventListener('click', function (e) {
      var btn = e.target.closest('.timer-dismiss-btn');
      if (!btn) return;
      var timerId = btn.dataset.timerId;
      _removeTimer(timerId);
    });

    // Timer trigger button clicks
    document.addEventListener('click', function (e) {
      var btn = e.target.closest('.timer-trigger-btn');
      if (!btn) return;
      e.stopPropagation();
      var seconds = parseInt(btn.dataset.seconds, 10);
      var label = btn.dataset.label || 'Timer';
      if (seconds > 0 && seconds <= 86400) {
        _startTimer(label, seconds);
      }
    });
  }

  // Visibility change — catch up timers after phone sleep
  if (!initDocumentDelegation._visibilityBound) {
    initDocumentDelegation._visibilityBound = true;
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible') {
        _tickAllTimers();
        // Re-acquire wake lock after tab becomes visible (browser auto-releases on hide)
        if (_cookingState.active) {
          _acquireWakeLock();
        }
      }
    });
  }
}

// --- Import Form ---
function initImportForm() {
  var form = document.getElementById('importForm');
  if (!form || form._initialized) return;
  form._initialized = true;

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var url = form.querySelector('[name=url]').value;
    var btn = form.querySelector('button');
    btn.textContent = 'Importing...';
    btn.disabled = true;

    fetch('/api/recipes/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: url }),
    })
      .then(function (r) {
        if (!r.ok)
          return r.json().then(function (d) {
            throw new Error(d.detail || 'Import failed');
          });
        return r.json();
      })
      .then(function (data) {
        window.location.href = '/edit/' + data.recipe.id;
      })
      .catch(function (err) {
        alert(err.message);
        btn.textContent = 'Import';
        btn.disabled = false;
      });
  });
}

// --- Paprika Import Form (double-submit guard) ---
function initPaprikaImportForm() {
  var form = document.getElementById('paprikaImportForm');
  if (!form || form._initialized) return;
  form._initialized = true;

  form.addEventListener('submit', function (e) {
    if (form._submitting) {
      e.preventDefault();
      return;
    }
    form._submitting = true;
    var btn = document.getElementById('paprikaImportBtn');
    if (btn) {
      btn.textContent = 'Importing...';
      btn.disabled = true;
    }
    // Form submits normally (not fetch — it's a regular POST)
  });
}

// --- Cooking Mode ---
function initCookingMode() {
  var btn = document.getElementById('cookingModeBtn');
  if (!btn) return;

  _cookingState.recipeId = btn.dataset.recipeId;

  // Restore strikethrough state from localStorage
  _restoreCookingState();

  // Check if any items are struck through (resume cooking)
  var hasState = document.querySelector('.ingredient-item.strikethrough');
  if (hasState) {
    _cookingState.active = true;
    btn.textContent = 'Done Cooking';
    document.body.classList.add('cooking-mode');
  }

  // Restore step state if resuming
  if (_cookingState.active) {
    _restoreStepState();
  }

  // Toggle cooking mode button — guard against duplicate listeners
  if (!btn._initialized) {
    btn._initialized = true;
    btn.addEventListener('click', function () {
      if (_cookingState.active) {
        // Clear all cooking state
        var items = document.querySelectorAll('.ingredient-item');
        items.forEach(function (li) {
          li.classList.remove('strikethrough');
          localStorage.removeItem(
            'cooking-' + _cookingState.recipeId + '-ingredient-' + li.dataset.index
          );
        });
        // Clear step state
        var steps = document.querySelectorAll('.direction-step');
        steps.forEach(function (s) {
          s.classList.remove('active-step', 'completed-step');
        });
        localStorage.removeItem('cooking-' + _cookingState.recipeId + '-step');
        _cookingState.active = false;
        _releaseWakeLock();
        btn.textContent = 'Start Cooking';
        document.body.classList.remove('cooking-mode');
      } else {
        _cookingState.active = true;
        _acquireWakeLock();
        btn.textContent = 'Done Cooking';
        document.body.classList.add('cooking-mode');
        // Auto-activate step 1
        var firstStep = document.querySelector('.direction-step');
        if (firstStep) {
          _setActiveStep(firstStep);
        }
      }
    });
  }
}

function _restoreCookingState() {
  if (!_cookingState.recipeId) return;
  var items = document.querySelectorAll('.ingredient-item');
  items.forEach(function (li) {
    var key = 'cooking-' + _cookingState.recipeId + '-ingredient-' + li.dataset.index;
    if (localStorage.getItem(key) === '1') {
      li.classList.add('strikethrough');
    }
  });
}

// --- Step Navigation ---
function _setActiveStep(stepEl) {
  var steps = document.querySelectorAll('.direction-step');
  var targetIdx = parseInt(stepEl.dataset.step, 10);

  steps.forEach(function (s) {
    var idx = parseInt(s.dataset.step, 10);
    s.classList.remove('active-step');
    if (idx < targetIdx) {
      s.classList.add('completed-step');
    } else {
      s.classList.remove('completed-step');
    }
  });
  stepEl.classList.add('active-step');
  stepEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

  // Persist
  if (_cookingState.recipeId) {
    try {
      localStorage.setItem('cooking-' + _cookingState.recipeId + '-step', String(targetIdx));
    } catch (e) { /* localStorage full — ignore */ }
  }
}

function _restoreStepState() {
  if (!_cookingState.recipeId || !_cookingState.active) return;
  var saved = localStorage.getItem('cooking-' + _cookingState.recipeId + '-step');
  if (saved === null) return;
  var idx = parseInt(saved, 10);
  var step = document.querySelector('.direction-step[data-step="' + idx + '"]');
  if (step) {
    _setActiveStep(step);
  }
}

// --- Recipe Scaling (client-side) ---
function initScaling() {
  var scaleButtons = document.getElementById('scaleButtons');
  if (!scaleButtons || scaleButtons._scalingInitialized) return;
  scaleButtons._scalingInitialized = true;

  var ingredientList = document.getElementById('ingredientList');
  var rawIngredients;

  try {
    rawIngredients = JSON.parse(scaleButtons.dataset.ingredients);
  } catch (e) {
    return;
  }

  var buttons = scaleButtons.querySelectorAll('.scale-btn');
  buttons.forEach(function (btn) {
    btn.addEventListener('click', function () {
      var factor = parseFloat(btn.dataset.factor);
      buttons.forEach(function (b) {
        b.classList.remove('active');
      });
      btn.classList.add('active');
      applyScaling(factor);
    });
  });

  function applyScaling(factor) {
    var items = ingredientList.querySelectorAll('.ingredient-item');
    items.forEach(function (li, i) {
      if (i >= rawIngredients.length) return;
      if (factor === 1) {
        li.textContent = rawIngredients[i];
      } else {
        li.textContent = scaleIngredientText(rawIngredients[i], factor);
      }
    });

    // Re-apply cooking mode strikethrough after scaling re-render
    _restoreCookingState();
  }

  function scaleIngredientText(text, factor) {
    return text.replace(
      /^(\d+(?:\.\d+)?(?:\s*\/\s*\d+)?(?:\s*-\s*\d+(?:\.\d+)?(?:\s*\/\s*\d+)?)?)/,
      function (match) {
        if (match.includes('-')) {
          var parts = match.split('-');
          return formatNumber(parseFraction(parts[0].trim()) * factor) +
            '-' + formatNumber(parseFraction(parts[1].trim()) * factor);
        }
        return formatNumber(parseFraction(match.trim()) * factor);
      }
    );
  }

  function parseFraction(s) {
    if (s.includes('/')) {
      var parts = s.split('/');
      return parseFloat(parts[0]) / parseFloat(parts[1]);
    }
    return parseFloat(s) || 0;
  }

  function formatNumber(n) {
    if (n === 0) return '0';
    var fractions = [
      [0.125, '1/8'], [0.25, '1/4'], [0.333, '1/3'],
      [0.5, '1/2'], [0.667, '2/3'], [0.75, '3/4'],
    ];

    var whole = Math.floor(n);
    var frac = n - whole;

    if (frac < 0.05) return String(whole || n.toFixed(0));

    for (var i = 0; i < fractions.length; i++) {
      if (Math.abs(frac - fractions[i][0]) < 0.05) {
        return whole > 0
          ? whole + ' ' + fractions[i][1]
          : fractions[i][1];
      }
    }

    return n.toFixed(1).replace(/\.0$/, '');
  }
}

// --- Quick Rate (star rating click handler) ---
function initQuickRate() {
  if (initQuickRate._bound) return;
  initQuickRate._bound = true;

  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.rating-star-btn');
    if (!btn) return;
    var widget = btn.closest('#rating-widget');
    if (!widget) return;
    var input = widget.querySelector('#ratingValue');
    if (input) input.value = btn.dataset.rating;
  });
}

// --- Calendar ---
function _clearCalendarForm() {
  var form = document.getElementById('add-recipe-form');
  if (!form) return;
  var dateInput = form.querySelector('[name="date"]');
  var slotInput = form.querySelector('[name="meal_slot"]');
  if (dateInput) dateInput.value = '';
  if (slotInput) slotInput.value = '';
}

function initCalendar() {
  var grid = document.getElementById('calendar-grid');
  if (!grid || grid._calendarInitialized) return;
  grid._calendarInitialized = true;

  // Event delegation: one listener on grid for all "+" buttons
  var form = document.getElementById('add-recipe-form');
  grid.addEventListener('click', function (e) {
    var addBtn = e.target.closest('.calendar-add-btn');
    if (!addBtn || !form) return;

    var dateInput = form.querySelector('[name="date"]');
    var slotInput = form.querySelector('[name="meal_slot"]');
    if (dateInput) dateInput.value = addBtn.dataset.date;
    if (slotInput) slotInput.value = addBtn.dataset.slot;

    form.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
}

// --- Nutrition Rows (dynamic add) ---
function initNutritionRows() {
  var addBtn = document.getElementById('addNutritionRow');
  if (!addBtn || addBtn._initialized) return;
  addBtn._initialized = true;

  addBtn.addEventListener('click', function () {
    var container = document.getElementById('nutritionRows');
    var row = document.createElement('div');
    row.className = 'nutrition-row';
    row.innerHTML =
      '<input type="text" name="nutrition_key" placeholder="Key" class="input">' +
      '<input type="text" name="nutrition_value" placeholder="Value" class="input">';
    container.appendChild(row);
  });
}

// ---------------------------------------------------------------------------
// Timer Detection (client-side — security requirement)
// ---------------------------------------------------------------------------


function initTimerTriggers() {
  var steps = document.querySelectorAll('.direction-step');
  steps.forEach(function (step) {
    if (step._timerScanned) return;
    step._timerScanned = true;

    var text = step.textContent;
    var matches = [];

    // Pattern 1: "for X minutes/hours"
    var re1 = /\bfor\s+(\d+)\s*(minutes?|mins?|hours?|hrs?)\b/gi;
    var m;
    while ((m = re1.exec(text)) !== null) {
      var val = parseInt(m[1], 10);
      var unit = m[2].toLowerCase();
      var seconds = (unit.charAt(0) === 'h') ? val * 3600 : val * 60;
      if (seconds > 0 && seconds <= 86400) {
        matches.push({ text: m[0], seconds: seconds, index: m.index });
      }
    }

    // Pattern 2: "N hour(s) N minute(s)" / "NhNm"
    var re2 = /\b(\d+)\s*(?:hours?|hrs?)\s*(?:and\s*)?(\d+)\s*(?:minutes?|mins?)\b/gi;
    while ((m = re2.exec(text)) !== null) {
      var hrs = parseInt(m[1], 10);
      var mins = parseInt(m[2], 10);
      var secs = hrs * 3600 + mins * 60;
      if (secs > 0 && secs <= 86400) {
        // Avoid duplicate if already matched by pattern 1
        var isDup = matches.some(function (existing) {
          return Math.abs(existing.index - m.index) < m[0].length;
        });
        if (!isDup) {
          matches.push({ text: m[0], seconds: secs, index: m.index });
        }
      }
    }

    var re3 = /\b(\d+)h\s*(\d+)m\b/gi;
    while ((m = re3.exec(text)) !== null) {
      var h3 = parseInt(m[1], 10);
      var m3 = parseInt(m[2], 10);
      var s3 = h3 * 3600 + m3 * 60;
      if (s3 > 0 && s3 <= 86400) {
        matches.push({ text: m[0], seconds: s3, index: m.index });
      }
    }

    if (matches.length === 0) return;

    // Sort by position descending so we can insert without shifting indices
    matches.sort(function (a, b) { return b.index - a.index; });

    // Replace text with buttons using safe DOM manipulation
    var html = step.textContent;
    matches.forEach(function (match) {
      var before = html.substring(0, match.index);
      var after = html.substring(match.index + match.text.length);
      // Create button text safely
      var label = match.text.trim();
      var btnPlaceholder = '{{TIMER_BTN_' + match.index + '}}';
      html = before + btnPlaceholder + after;
    });

    // Now build DOM
    step.textContent = '';
    var parts = html.split(/\{\{TIMER_BTN_\d+\}\}/);
    // Re-sort matches by index ascending for DOM building
    matches.sort(function (a, b) { return a.index - b.index; });

    for (var i = 0; i < parts.length; i++) {
      if (parts[i]) {
        step.appendChild(document.createTextNode(parts[i]));
      }
      if (i < matches.length) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'timer-trigger-btn';
        btn.dataset.seconds = matches[i].seconds;
        btn.dataset.label = matches[i].text.trim();
        btn.textContent = matches[i].text.trim();
        step.appendChild(btn);
      }
    }
  });
}

// ---------------------------------------------------------------------------
// Timer Engine
// ---------------------------------------------------------------------------

function _generateId() {
  return 'timer-' + Date.now() + '-' + Math.random().toString(36).substr(2, 6);
}

function _startTimer(label, seconds) {
  // Ensure AudioContext on user gesture
  _ensureAudioCtx();

  var timer = {
    id: _generateId(),
    name: label,
    endTime: Date.now() + seconds * 1000,
    originalSeconds: seconds,
    fired: false,
    createdAt: Date.now()
  };

  _timers.push(timer);
  _saveTimerToStorage(timer);
  _ensureTimerTick();
  _renderTimerPanel();
}

function _removeTimer(timerId) {
  _timers = _timers.filter(function (t) { return t.id !== timerId; });
  try { localStorage.removeItem(timerId); } catch (e) {}
  _renderTimerPanel();
  if (_timers.length === 0) {
    _stopTimerTick();
  }
}

function _saveTimerToStorage(timer) {
  try {
    localStorage.setItem(timer.id, JSON.stringify(timer));
  } catch (e) { /* localStorage full or unavailable */ }
}

function _ensureTimerTick() {
  if (_timerIntervalId !== null) return;
  _timerIntervalId = setInterval(_tickAllTimers, 1000);
}

function _stopTimerTick() {
  if (_timerIntervalId === null) return;
  clearInterval(_timerIntervalId);
  _timerIntervalId = null;
}

function _tickAllTimers() {
  var now = Date.now();
  var newlyExpired = [];

  for (var i = 0; i < _timers.length; i++) {
    var t = _timers[i];
    if (!t.fired && now >= t.endTime) {
      t.fired = true;
      _saveTimerToStorage(t);
      newlyExpired.push(t);
    }
  }

  // Fire single beep for all newly expired (prevent stacking)
  if (newlyExpired.length > 0 && !_isBeeping) {
    _playBeep();
  }

  _renderTimerPanel();
}

function _hydrateTimers() {
  var now = Date.now();
  var staleThreshold = 24 * 60 * 60 * 1000; // 24 hours

  for (var i = 0; i < localStorage.length; i++) {
    var key = localStorage.key(i);
    if (!key || !key.startsWith('timer-')) continue;

    try {
      var data = JSON.parse(localStorage.getItem(key));
      // Validate
      if (!data || typeof data.endTime !== 'number' || data.endTime <= 0 ||
          typeof data.originalSeconds !== 'number' ||
          data.originalSeconds < 1 || data.originalSeconds > 86400) {
        localStorage.removeItem(key);
        continue;
      }
      // 24-hour stale cleanup
      if (data.createdAt && now - data.createdAt > staleThreshold) {
        localStorage.removeItem(key);
        continue;
      }
      // Check if already expired
      if (now >= data.endTime) {
        data.fired = true;
      }
      _timers.push(data);
    } catch (e) {
      localStorage.removeItem(key);
    }
  }

  if (_timers.length > 0) {
    _ensureTimerTick();
    _renderTimerPanel();
    // Fire beeps for already-expired unfired
    var unfired = _timers.filter(function (t) { return t.fired; });
    if (unfired.length > 0 && !_isBeeping) {
      _playBeep();
    }
  }
}

function _renderTimerPanel() {
  var panel = document.getElementById('timer-panel');
  if (!panel) return;

  if (_timers.length === 0) {
    panel.style.display = 'none';
    return;
  }

  panel.style.display = '';
  var countEl = panel.querySelector('.timer-count');
  if (countEl) countEl.textContent = _timers.length;

  var listEl = panel.querySelector('.timer-list');
  if (!listEl) return;

  var now = Date.now();

  // Clear and rebuild list content
  while (listEl.firstChild) listEl.removeChild(listEl.firstChild);
  for (var j = 0; j < _timers.length; j++) {
    var t2 = _timers[j];
    var rem2 = Math.max(0, Math.ceil((t2.endTime - now) / 1000));
    var str2 = t2.fired ? 'DONE' : _formatSeconds(rem2);
    var cls2 = t2.fired ? ' expired' : '';

    var e2 = document.createElement('div');
    e2.className = 'timer-entry';

    var i2 = document.createElement('div');
    i2.className = 'timer-entry-info';

    var l2 = document.createElement('span');
    l2.className = 'timer-entry-label';
    l2.textContent = t2.name;

    var tm2 = document.createElement('span');
    tm2.className = 'timer-entry-time' + cls2;
    tm2.textContent = str2;

    i2.appendChild(l2);
    i2.appendChild(tm2);

    var d2 = document.createElement('button');
    d2.className = 'timer-dismiss-btn';
    d2.dataset.timerId = t2.id;
    d2.textContent = '\u00D7';
    d2.setAttribute('aria-label', 'Dismiss timer');

    e2.appendChild(i2);
    e2.appendChild(d2);
    listEl.appendChild(e2);
  }
}

function _formatSeconds(s) {
  var h = Math.floor(s / 3600);
  var m = Math.floor((s % 3600) / 60);
  var sec = s % 60;
  if (h > 0) {
    return h + ':' + (m < 10 ? '0' : '') + m + ':' + (sec < 10 ? '0' : '') + sec;
  }
  return m + ':' + (sec < 10 ? '0' : '') + sec;
}

// ---------------------------------------------------------------------------
// Web Audio Alert
// ---------------------------------------------------------------------------

function _ensureAudioCtx() {
  if (_audioCtx && _audioCtx.state !== 'closed') return;
  try {
    _audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  } catch (e) {
    _audioCtx = null;
  }
}

function _playBeep() {
  if (_isBeeping) return;
  if (!_audioCtx) {
    // Visual-only fallback
    return;
  }

  _isBeeping = true;

  // Resume if suspended
  if (_audioCtx.state === 'suspended') {
    _audioCtx.resume().then(function () { _doBeep(); });
  } else if (_audioCtx.state === 'closed') {
    _ensureAudioCtx();
    if (_audioCtx) _doBeep();
    else _isBeeping = false;
  } else {
    _doBeep();
  }
}

var _beepCancelToken = { canceled: false };

function _doBeep() {
  var beepCount = 0;
  var maxBeeps = 5;
  _beepCancelToken = { canceled: false };
  var token = _beepCancelToken;

  function singleBeep() {
    if (token.canceled || beepCount >= maxBeeps || !_audioCtx || _audioCtx.state === 'closed') {
      _isBeeping = false;
      return;
    }
    beepCount++;

    var osc = _audioCtx.createOscillator();
    var gain = _audioCtx.createGain();
    osc.connect(gain);
    gain.connect(_audioCtx.destination);

    osc.frequency.value = 880;
    osc.type = 'sine';
    gain.gain.setValueAtTime(0.3, _audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.01, _audioCtx.currentTime + 0.2);

    osc.start(_audioCtx.currentTime);
    osc.stop(_audioCtx.currentTime + 0.2);

    setTimeout(singleBeep, 400); // 200ms on + 200ms off
  }

  singleBeep();

  // Auto-stop after 60 seconds max
  setTimeout(function () { _isBeeping = false; }, 60000);
}

function _stopBeeping() {
  _beepCancelToken.canceled = true;
  _isBeeping = false;
}

// ---------------------------------------------------------------------------
// Grocery Filter
// ---------------------------------------------------------------------------

function initGroceryFilter() {
  var toggle = document.getElementById('hideCheckedToggle');
  var itemsList = document.getElementById('items-list');
  if (!toggle || !itemsList) return;
  if (toggle._filterBound) return;
  toggle._filterBound = true;

  toggle.addEventListener('change', function () {
    if (toggle.checked) {
      itemsList.classList.add('grocery-hide-checked');
    } else {
      itemsList.classList.remove('grocery-hide-checked');
    }
    _updateGroceryRemaining();
    _updateAisleEmptyState();
  });

  _updateGroceryRemaining();
}

function _updateGroceryRemaining() {
  var el = document.getElementById('grocery-remaining');
  if (!el) return;
  var total = document.querySelectorAll('.grocery-item').length;
  var checked = document.querySelectorAll('.grocery-item.checked').length;
  var remaining = total - checked;
  el.textContent = remaining + ' of ' + total + ' remaining';
}

function _updateAisleEmptyState() {
  var sections = document.querySelectorAll('.aisle-section');
  sections.forEach(function (section) {
    var visible = section.querySelectorAll('.grocery-item:not(.checked)').length;
    if (visible === 0 && document.getElementById('hideCheckedToggle').checked) {
      section.classList.add('aisle-empty');
    } else {
      section.classList.remove('aisle-empty');
    }
  });
}

// ---------------------------------------------------------------------------
// Wake Lock (keeps screen on during cooking mode)
// ---------------------------------------------------------------------------

var _wakeLockRequestId = 0;

function _acquireWakeLock() {
  if (!('wakeLock' in navigator) || !_cookingState.active) return;
  var myId = ++_wakeLockRequestId;
  navigator.wakeLock.request('screen').then(function (lock) {
    if (_wakeLockRequestId !== myId || !_cookingState.active) {
      lock.release();
      return;
    }
    _cookingState.wakeLock = lock;
  }).catch(function () { /* Permission denied or not supported */ });
}

function _releaseWakeLock() {
  _wakeLockRequestId++;
  if (_cookingState.wakeLock) {
    _cookingState.wakeLock.release();
    _cookingState.wakeLock = null;
  }
}
