/* PixelMint — upload UI (vanilla JS, no dependencies). */
(function () {
  "use strict";

  var form = document.getElementById("optimize-form");
  if (!form) return;

  var MAX_FILES = parseInt(form.dataset.maxFiles, 10) || 10;
  var MAX_BYTES = parseInt(form.dataset.maxBytes, 10) || 15 * 1024 * 1024;
  var EXTENSIONS = ["jpg", "jpeg", "png", "webp"];

  var dropzone = document.getElementById("dropzone");
  var input = document.getElementById("file-input");
  var errorList = document.getElementById("client-errors");
  var selection = document.getElementById("selection");
  var summary = document.getElementById("selection-summary");
  var previews = document.getElementById("previews");
  var clearAll = document.getElementById("clear-all");
  var submitBtn = document.getElementById("submit-btn");
  var submitLabel = document.getElementById("submit-label");
  var quality = document.getElementById("id_quality");
  var qualityValue = document.getElementById("quality-value");
  var qualityNote = document.getElementById("quality-note");
  var jpgNote = document.getElementById("jpg-note");
  var formatRadios = form.querySelectorAll('input[name="output_format"]');

  var files = []; // File objects currently selected

  function formatBytes(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function extensionOf(name) {
    var i = name.lastIndexOf(".");
    return i === -1 ? "" : name.slice(i + 1).toLowerCase();
  }

  function fileKey(f) {
    return f.name + "|" + f.size + "|" + f.lastModified;
  }

  function showErrors(messages) {
    errorList.innerHTML = "";
    messages.forEach(function (msg) {
      var li = document.createElement("li");
      li.textContent = msg;
      errorList.appendChild(li);
    });
    errorList.hidden = messages.length === 0;
  }

  function syncInput() {
    // Keep the real <input> in sync so the browser submits exactly these files.
    var dt = new DataTransfer();
    files.forEach(function (f) { dt.items.add(f); });
    input.files = dt.files;
  }

  function addFiles(incoming) {
    var problems = [];
    var known = {};
    files.forEach(function (f) { known[fileKey(f)] = true; });

    Array.prototype.forEach.call(incoming, function (f) {
      if (known[fileKey(f)]) return; // already selected
      if (EXTENSIONS.indexOf(extensionOf(f.name)) === -1) {
        problems.push(f.name + ": unsupported type. Use JPG, PNG or WebP.");
      } else if (f.size === 0) {
        problems.push(f.name + ": the file is empty.");
      } else if (f.size > MAX_BYTES) {
        problems.push(f.name + ": " + formatBytes(f.size) + " exceeds the " + Math.round(MAX_BYTES / 1048576) + " MB limit.");
      } else if (files.length >= MAX_FILES) {
        problems.push(f.name + ": not added — maximum " + MAX_FILES + " images per batch.");
      } else {
        files.push(f);
        known[fileKey(f)] = true;
      }
    });

    showErrors(problems);
    syncInput();
    render();
  }

  function removeFile(index) {
    files.splice(index, 1);
    showErrors([]);
    syncInput();
    render();
  }

  function render() {
    // Release old object URLs before rebuilding previews.
    Array.prototype.forEach.call(previews.querySelectorAll("img"), function (img) {
      URL.revokeObjectURL(img.src);
    });
    previews.innerHTML = "";

    files.forEach(function (file, index) {
      var li = document.createElement("li");
      li.className = "preview";

      var imgWrap = document.createElement("div");
      imgWrap.className = "pv-img";
      var img = document.createElement("img");
      img.alt = "Preview of " + file.name;
      img.src = URL.createObjectURL(file);
      imgWrap.appendChild(img);

      var meta = document.createElement("div");
      meta.className = "pv-meta";
      var name = document.createElement("div");
      name.className = "pv-name";
      name.textContent = file.name;
      name.title = file.name;
      var size = document.createElement("div");
      size.className = "pv-size";
      size.textContent = formatBytes(file.size);
      meta.appendChild(name);
      meta.appendChild(size);

      var remove = document.createElement("button");
      remove.type = "button";
      remove.className = "pv-remove";
      remove.setAttribute("aria-label", "Remove " + file.name);
      remove.textContent = "×";
      remove.addEventListener("click", function () { removeFile(index); });

      li.appendChild(imgWrap);
      li.appendChild(meta);
      li.appendChild(remove);
      previews.appendChild(li);
    });

    var total = files.reduce(function (sum, f) { return sum + f.size; }, 0);
    selection.hidden = files.length === 0;
    summary.textContent = files.length + " of " + MAX_FILES + " image" + (files.length === 1 ? "" : "s") +
      " selected · " + formatBytes(total);
    submitBtn.disabled = files.length === 0;
  }

  // --- Drag & drop -----------------------------------------------------------
  ["dragenter", "dragover"].forEach(function (type) {
    dropzone.addEventListener(type, function (e) {
      e.preventDefault();
      dropzone.classList.add("is-dragover");
    });
  });
  ["dragleave", "drop"].forEach(function (type) {
    dropzone.addEventListener(type, function (e) {
      e.preventDefault();
      dropzone.classList.remove("is-dragover");
    });
  });
  dropzone.addEventListener("drop", function (e) {
    if (e.dataTransfer && e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
  });
  // A file dropped outside the zone shouldn't make the browser navigate to it.
  ["dragover", "drop"].forEach(function (type) {
    window.addEventListener(type, function (e) {
      if (!dropzone.contains(e.target)) e.preventDefault();
    });
  });

  input.addEventListener("change", function () {
    // The picker replaces input.files; merge its choice into our list.
    addFiles(input.files);
  });
  input.tabIndex = -1;
  dropzone.addEventListener("keydown", function (e) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      input.click();
    }
  });
  clearAll.addEventListener("click", function () {
    files = [];
    showErrors([]);
    syncInput();
    render();
  });

  // --- Settings --------------------------------------------------------------
  function currentFormat() {
    var checked = form.querySelector('input[name="output_format"]:checked');
    return checked ? checked.value : "original";
  }
  function updateSettings() {
    qualityValue.textContent = quality.value;
    var min = parseFloat(quality.min), max = parseFloat(quality.max);
    quality.style.setProperty("--pct", ((quality.value - min) / (max - min) * 100) + "%");
    qualityNote.hidden = currentFormat() !== "png";
    jpgNote.hidden = currentFormat() !== "jpg";
  }
  quality.addEventListener("input", updateSettings);
  Array.prototype.forEach.call(formatRadios, function (radio) {
    radio.addEventListener("change", updateSettings);
  });

  // --- Submit ----------------------------------------------------------------
  function setLoading(isLoading) {
    submitBtn.classList.toggle("is-loading", isLoading);
    submitBtn.disabled = isLoading || files.length === 0;
    submitLabel.textContent = isLoading ? "Optimizing…" : "Optimize images";
    form.classList.toggle("is-busy", isLoading);
    form.setAttribute("aria-busy", isLoading ? "true" : "false");
  }

  form.addEventListener("submit", function (e) {
    if (files.length === 0) {
      e.preventDefault();
      showErrors(["Choose at least one image to optimize."]);
      return;
    }
    if (form.dataset.submitting === "1") {
      e.preventDefault();
      return;
    }
    form.dataset.submitting = "1";
    setLoading(true);
  });

  // Back/forward cache: restore a usable form.
  window.addEventListener("pageshow", function (e) {
    if (e.persisted) {
      form.dataset.submitting = "0";
      setLoading(false);
    }
  });

  updateSettings();
  render();
})();

