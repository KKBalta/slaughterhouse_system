(function () {
    var INDICATOR_ATTR = "data-required-indicator";
    var observer = null;

    function isRelevantControl(node) {
        if (!node || node.nodeType !== 1) {
            return false;
        }
        var tagName = node.tagName;
        if (tagName !== "INPUT" && tagName !== "SELECT" && tagName !== "TEXTAREA") {
            return false;
        }
        if (tagName === "INPUT") {
            var type = (node.getAttribute("type") || "text").toLowerCase();
            if (type === "hidden" || type === "submit" || type === "button" || type === "reset" || type === "image") {
                return false;
            }
        }
        return true;
    }

    function isRequiredControl(node) {
        return isRelevantControl(node) && !node.disabled && (node.required || node.getAttribute("aria-required") === "true");
    }

    function hasExistingIndicator(label) {
        if (label.querySelector("[" + INDICATOR_ATTR + "='true']")) {
            return true;
        }
        return /\*\s*$/.test((label.textContent || "").trim());
    }

    function ensureIndicator(label) {
        if (!label || label.classList.contains("sr-only") || hasExistingIndicator(label)) {
            return;
        }
        var indicator = document.createElement("span");
        indicator.setAttribute(INDICATOR_ATTR, "true");
        indicator.setAttribute("aria-hidden", "true");
        indicator.textContent = " *";
        indicator.style.color = "#dc2626";
        indicator.style.fontWeight = "600";
        label.appendChild(indicator);
    }

    function removeIndicator(label) {
        if (!label) {
            return;
        }
        var indicator = label.querySelector("[" + INDICATOR_ATTR + "='true']");
        if (indicator) {
            indicator.remove();
        }
    }

    function uniqueControls(nodes) {
        var seen = new Set();
        var controls = [];
        nodes.forEach(function (node) {
            if (!isRelevantControl(node) || seen.has(node)) {
                return;
            }
            seen.add(node);
            controls.push(node);
        });
        return controls;
    }

    function controlsForLabel(label) {
        if (!label || !label.closest("form")) {
            return [];
        }

        var controls = [];
        if (label.control) {
            controls.push(label.control);
        }

        var nestedControls = label.querySelectorAll("input, select, textarea");
        if (nestedControls.length) {
            controls = controls.concat(Array.prototype.slice.call(nestedControls));
        }

        if (controls.length) {
            return uniqueControls(controls);
        }

        if (label.htmlFor) {
            var explicitControl = document.getElementById(label.htmlFor);
            if (explicitControl) {
                return uniqueControls([explicitControl]);
            }
        }

        var container = label.parentElement;
        if (!container) {
            return [];
        }
        return uniqueControls(Array.prototype.slice.call(container.querySelectorAll("input, select, textarea")));
    }

    function syncRequiredFieldIndicators(root) {
        var scope = root || document;
        var labels = scope.querySelectorAll("form label");
        labels.forEach(function (label) {
            var controls = controlsForLabel(label);
            var shouldShow = controls.some(isRequiredControl);
            if (shouldShow) {
                ensureIndicator(label);
            } else {
                removeIndicator(label);
            }
        });
    }

    function scheduleSync() {
        window.requestAnimationFrame(function () {
            syncRequiredFieldIndicators(document);
        });
    }

    function init() {
        syncRequiredFieldIndicators(document);

        document.addEventListener("change", scheduleSync, true);
        document.addEventListener("input", scheduleSync, true);

        observer = new MutationObserver(function (mutations) {
            for (var i = 0; i < mutations.length; i += 1) {
                var mutation = mutations[i];
                if (mutation.type === "attributes" || mutation.addedNodes.length || mutation.removedNodes.length) {
                    scheduleSync();
                    return;
                }
            }
        });
        observer.observe(document.documentElement, {
            subtree: true,
            childList: true,
            attributes: true,
            attributeFilter: ["required", "aria-required", "disabled", "for", "id"],
        });

        window.syncRequiredFieldIndicators = syncRequiredFieldIndicators;
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init, { once: true });
    } else {
        init();
    }
})();
