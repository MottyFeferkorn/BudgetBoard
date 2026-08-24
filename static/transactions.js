const transactionForm = document.getElementById("add-transaction-form");
const transactionModalElement = document.getElementById("addTransactionModal");

if (transactionForm) {
    const formFields = transactionForm.querySelectorAll("input, select, textarea");

    // Recheck only fields that have already failed validation.
    function updateFieldState(field) {
        const validationStarted =
            field.classList.contains("is-invalid")
            || field.classList.contains("is-valid");

        if (!validationStarted) {
            return;
        }

        const fieldIsValid = field.checkValidity();
        field.classList.toggle("is-invalid", !fieldIsValid);
        field.classList.toggle("is-valid", fieldIsValid);
    }

    formFields.forEach(function (field) {
        field.addEventListener("input", function () {
            updateFieldState(field);
        });

        field.addEventListener("change", function () {
            updateFieldState(field);
        });
    });

    // Mark only invalid fields red and submit valid forms without a green flash.
    transactionForm.addEventListener("submit", function (event) {
        if (transactionForm.checkValidity()) {
            return;
        }

        event.preventDefault();
        event.stopPropagation();

        const invalidFields = transactionForm.querySelectorAll(":invalid");

        invalidFields.forEach(function (field) {
            field.classList.remove("is-valid");
            field.classList.add("is-invalid");
        });

        invalidFields[0]?.focus();
    });

    // Reopen the modal when Flask returns field-specific backend errors.
    if (transactionForm.dataset.hasErrors === "true" && transactionModalElement) {
        const transactionModal = new bootstrap.Modal(transactionModalElement);
        transactionModal.show();
    }
}


const filterForm = document.getElementById("transaction-filter-form");
const searchInput = document.getElementById("transaction-search-input");
const clearFilters = document.getElementById("transaction-filter-clear");
const resultsCard = document.getElementById("transaction-results-card");

let filterTimer;
let activeRequest;


// Build a URL containing every nonempty form value.
function buildFilterUrl() {
    const formData = new FormData(filterForm);
    const parameters = new URLSearchParams();

    for (const [name, value] of formData.entries()) {
        const cleanValue = String(value).trim();

        if (cleanValue) {
            parameters.append(name, cleanValue);
        }
    }

    const url = new URL(filterForm.action, window.location.origin);
    url.search = parameters.toString();

    return url;
}


// Keep the category and account count badges in sync with their checkboxes.
function updateFilterCounts() {
    const categoryCount = filterForm.querySelectorAll(
        'input[name="category"]:checked'
    ).length;

    const accountCount = filterForm.querySelectorAll(
        'input[name="account"]:checked'
    ).length;

    const categoryBadge = document.getElementById("category-filter-count");
    const accountBadge = document.getElementById("account-filter-count");

    if (categoryBadge) {
        categoryBadge.textContent = categoryCount;
        categoryBadge.classList.toggle("d-none", categoryCount === 0);
    }

    if (accountBadge) {
        accountBadge.textContent = accountCount;
        accountBadge.classList.toggle("d-none", accountCount === 0);
    }
}


// Fetch the filtered transaction page and replace only its table, errors, and pagination.
async function loadTransactionResults(url, updateUrl = true) {
    activeRequest?.abort();

    const requestController = new AbortController();
    activeRequest = requestController;

    resultsCard?.classList.add("transaction-is-loading");
    resultsCard?.setAttribute("aria-busy", "true");

    try {
        const response = await fetch(url, {
            headers: {
                "X-Requested-With": "XMLHttpRequest"
            },
            signal: requestController.signal
        });

        if (!response.ok) {
            throw new Error(`Transaction request failed: ${response.status}`);
        }

        const html = await response.text();
        const nextPage = new DOMParser().parseFromString(html, "text/html");

        const currentBody = document.getElementById("transaction-results-body");
        const nextBody = nextPage.getElementById("transaction-results-body");
        const currentPagination = document.getElementById("transaction-pagination");
        const nextPagination = nextPage.getElementById("transaction-pagination");
        const currentErrors = document.getElementById("transaction-filter-errors");
        const nextErrors = nextPage.getElementById("transaction-filter-errors");

        if (!currentBody || !nextBody || !currentPagination || !nextPagination) {
            window.location.assign(url);
            return;
        }

        currentBody.innerHTML = nextBody.innerHTML;
        currentPagination.innerHTML = nextPagination.innerHTML;

        if (currentErrors) {
            currentErrors.innerHTML = nextErrors?.innerHTML || "";
        }

        if (updateUrl) {
            window.history.replaceState({}, "", url);
        }
    } catch (error) {
        if (error.name !== "AbortError") {
            // Full navigation remains the fallback if an asynchronous update fails.
            window.location.assign(url);
        }
    } finally {
        if (activeRequest === requestController) {
            resultsCard?.classList.remove("transaction-is-loading");
            resultsCard?.removeAttribute("aria-busy");
        }
    }
}


// Apply current filters after the requested delay.
function scheduleFilterUpdate(delay = 0) {
    window.clearTimeout(filterTimer);

    filterTimer = window.setTimeout(function () {
        if (!filterForm.checkValidity()) {
            return;
        }

        updateFilterCounts();
        loadTransactionResults(buildFilterUrl());
    }, delay);
}


if (filterForm) {
    // Search after typing pauses briefly.
    searchInput?.addEventListener("input", function () {
        scheduleFilterUpdate(350);
    });

    // Pressing Enter applies the current filters immediately.
    filterForm.addEventListener("submit", function (event) {
        event.preventDefault();

        if (!filterForm.checkValidity()) {
            filterForm.reportValidity();
            return;
        }

        window.clearTimeout(filterTimer);
        updateFilterCounts();
        loadTransactionResults(buildFilterUrl());
    });

    // Checkbox, date, and sorting changes apply immediately.
    filterForm.querySelectorAll(
        'input[type="checkbox"], input[type="date"], select'
    ).forEach(function (control) {
        control.addEventListener("change", function () {
            scheduleFilterUpdate();
        });
    });

    // Amount changes wait briefly so requests are not sent for every keystroke.
    filterForm.querySelectorAll('input[type="number"]').forEach(function (control) {
        control.addEventListener("input", function () {
            scheduleFilterUpdate(350);
        });
    });

    // Clear every filter without requiring a full-page refresh.
    clearFilters?.addEventListener("click", function (event) {
        event.preventDefault();

        filterForm.querySelectorAll("[name]").forEach(function (control) {
            if (control.type === "checkbox" || control.type === "radio") {
                control.checked = false;
            } else if (control.name === "sort") {
                control.value = "newest";
            } else {
                control.value = "";
            }
        });

        updateFilterCounts();

        loadTransactionResults(
            new URL(clearFilters.href, window.location.origin)
        );
    });

    // Load More and Load All use the same asynchronous table replacement.
    document.addEventListener("click", function (event) {
        const paginationLink = event.target.closest("#transaction-pagination a");

        if (!paginationLink) {
            return;
        }

        event.preventDefault();
        loadTransactionResults(new URL(paginationLink.href));
    });

    updateFilterCounts();
}
