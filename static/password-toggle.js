document.querySelectorAll("[data-password-toggle]").forEach(function (button) {
    const passwordInput = document.querySelector(button.dataset.passwordToggle);
    const icon = button.querySelector("i");

    if (!passwordInput || !icon) {
        return;
    }

    button.addEventListener("click", function () {
        const passwordIsVisible = passwordInput.type === "text";

        passwordInput.type = passwordIsVisible ? "password" : "text";
        icon.classList.toggle("bi-eye", passwordIsVisible);
        icon.classList.toggle("bi-eye-slash", !passwordIsVisible);

        button.setAttribute("aria-pressed", String(!passwordIsVisible));
        button.setAttribute(
            "aria-label",
            passwordIsVisible ? "Show password" : "Hide password"
        );
        button.title = passwordIsVisible ? "Show password" : "Hide password";
    });
});
