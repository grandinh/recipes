/**
 * Recipe Manager — client-side JS
 * Handles: import form, cooking mode, recipe scaling, nutrition rows.
 * All inline scripts have been moved here for CSP compliance.
 */

document.addEventListener('DOMContentLoaded', function () {
  initImportForm();
  initCookingMode();
  initScaling();
  initNutritionRows();
});

// --- Import Form ---
function initImportForm() {
  var form = document.getElementById('importForm');
  if (!form) return;

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
function initCookingMode() {
  var btn = document.getElementById('cookingModeBtn');
  if (!btn) return;

  var recipeId = btn.dataset.recipeId;
  var isCooking = false;

  // Restore state
  var ingredients = document.querySelectorAll('.ingredient-item');
  ingredients.forEach(function (li) {
    var key = 'cooking-' + recipeId + '-ingredient-' + li.dataset.index;
    if (localStorage.getItem(key) === '1') {
      li.classList.add('strikethrough');
    }
  });

  // Check if any items are struck through (resume cooking)
  var hasState = Array.from(ingredients).some(function (li) {
    return li.classList.contains('strikethrough');
  });
  if (hasState) {
    isCooking = true;
    btn.textContent = 'Done Cooking';
    document.body.classList.add('cooking-mode');
  }

  btn.addEventListener('click', function () {
    if (isCooking) {
      // Clear cooking state
      ingredients.forEach(function (li) {
        li.classList.remove('strikethrough');
        localStorage.removeItem(
          'cooking-' + recipeId + '-ingredient-' + li.dataset.index
        );
      });
      isCooking = false;
      btn.textContent = 'Start Cooking';
      document.body.classList.remove('cooking-mode');
    } else {
      isCooking = true;
      btn.textContent = 'Done Cooking';
      document.body.classList.add('cooking-mode');
    }
  });

  // Ingredient click toggles strikethrough
  ingredients.forEach(function (li) {
    li.addEventListener('click', function () {
      if (!isCooking) return;
      li.classList.toggle('strikethrough');
      var key = 'cooking-' + recipeId + '-ingredient-' + li.dataset.index;
      if (li.classList.contains('strikethrough')) {
        localStorage.setItem(key, '1');
      } else {
        localStorage.removeItem(key);
      }
    });
  });

  // Sync across tabs
  window.addEventListener('storage', function (e) {
    if (!e.key || !e.key.startsWith('cooking-' + recipeId)) return;
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

// --- Recipe Scaling (client-side) ---
function initScaling() {
  var scaleButtons = document.getElementById('scaleButtons');
  if (!scaleButtons) return;

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
    var recipeId = scaleButtons.dataset.recipeId;
    items.forEach(function (li) {
      var key = 'cooking-' + recipeId + '-ingredient-' + li.dataset.index;
      if (localStorage.getItem(key) === '1') {
        li.classList.add('strikethrough');
      }
    });
  }

  function scaleIngredientText(text, factor) {
    // Simple client-side scaling: find leading numbers/fractions and multiply
    return text.replace(
      /^(\d+(?:\.\d+)?(?:\s*\/\s*\d+)?(?:\s*-\s*\d+(?:\.\d+)?(?:\s*\/\s*\d+)?)?)/,
      function (match) {
        // Handle ranges like "2-3"
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
    // Common cooking fractions
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

    // No matching fraction — show decimal rounded to 1 place
    return n.toFixed(1).replace(/\.0$/, '');
  }
}

// --- Nutrition Rows (dynamic add) ---
function initNutritionRows() {
  var addBtn = document.getElementById('addNutritionRow');
  if (!addBtn) return;

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
