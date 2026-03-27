/**
 * Recipe Manager — client-side JS
 * Handles: import form, cooking mode, recipe scaling, nutrition rows, quick rate.
 * All inline scripts have been moved here for CSP compliance.
 *
 * All init functions are idempotent (safe to call multiple times) so they
 * can re-run after HTMX swaps and hx-boost navigation without duplicating
 * event listeners.
 */

document.addEventListener('DOMContentLoaded', function () {
  initAll();
  initHtmxHandlers();
});

function initAll() {
  initImportForm();
  initCookingMode();
  initScaling();
  initNutritionRows();
  initQuickRate();
  initCalendar();
}

// --- HTMX lifecycle handlers ---
function initHtmxHandlers() {
  // Re-init after HTMX swaps (partial updates and hx-boost navigation)
  document.body.addEventListener('htmx:afterSettle', function (evt) {
    var target = evt.detail.target;
    // Boosted navigation replaces <main> content — re-init everything
    if (target.tagName === 'MAIN' || target.closest('main')) {
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
    }
  });

  // Browser back/forward with hx-push-url — re-init after history restoration
  document.body.addEventListener('htmx:historyRestore', function () {
    initAll();
  });
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

// --- Cooking Mode ---
// Uses event delegation on document so listeners survive HTMX swaps
// of the scaling section (which replaces #ingredientList).
var _cookingState = { active: false, recipeId: null };

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
        _cookingState.active = false;
        btn.textContent = 'Start Cooking';
        document.body.classList.remove('cooking-mode');
      } else {
        _cookingState.active = true;
        btn.textContent = 'Done Cooking';
        document.body.classList.add('cooking-mode');
      }
    });
  }

  // Ingredient click — event delegation on document (bound once, survives swaps)
  if (!initCookingMode._delegated) {
    initCookingMode._delegated = true;
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
// Sets hidden input value before HTMX fires the request.
// Uses event delegation — bound once, survives swaps.
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

// --- Calendar Meal Plan ---
// Uses event delegation on the grid element — survives HTMX swaps.
// Flag is on the grid element itself which gets destroyed on swap,
// so initCalendar() correctly re-initializes after each grid replacement.
function initCalendar() {
  var grid = document.getElementById('calendar-grid');
  if (!grid || grid._calendarInitialized) return;
  grid._calendarInitialized = true;

  // Reset stale form fields on every grid swap
  var form = document.getElementById('add-recipe-form');
  if (form) {
    var dateInput = form.querySelector('[name="date"]');
    var slotInput = form.querySelector('[name="meal_slot"]');
    if (dateInput) dateInput.value = '';
    if (slotInput) slotInput.value = '';
  }

  // Event delegation: one listener on grid for all "+" buttons
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
