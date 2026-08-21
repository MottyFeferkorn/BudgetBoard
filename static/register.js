const registerForm = document.getElementById("register-form");

if (registerForm) {
    const emailInput = document.getElementById("email");
    const passwordInput = document.getElementById("password");
    const confirmationInput = document.getElementById("confirmation");

    const emailFeedback = document.getElementById("email-feedback");
    const passwordFeedback = document.getElementById("password-feedback");
    const confirmationFeedback = document.getElementById("confirmation-feedback");

    // Apply Bootstrap's validation state and update the field's feedback message.
    function setFieldState(input, feedback, message) {
        input.classList.remove("is-valid", "is-invalid");

        if (message) {
            input.classList.add("is-invalid");
            feedback.textContent = message;
            return false;
        }

        input.classList.add("is-valid");
        feedback.textContent = "";
        return true;
    }

    // Check that the email is present and satisfies the browser's email rules.
    function validateEmail() {
        if (!emailInput.value.trim()) {
            return setFieldState(
                emailInput,
                emailFeedback,
                "Please enter your email address."
            );
        }

        if (!emailInput.validity.valid) {
            return setFieldState(
                emailInput,
                emailFeedback,
                "Please enter a valid email address."
            );
        }

        return setFieldState(emailInput, emailFeedback, "");
    }

    // Mirror the backend's minimum password length requirement.
    function validatePassword() {
        if (!passwordInput.value) {
            return setFieldState(
                passwordInput,
                passwordFeedback,
                "Please enter a password."
            );
        }

        if (passwordInput.value.length < 8) {
            return setFieldState(
                passwordInput,
                passwordFeedback,
                "Password must contain at least 8 characters."
            );
        }

        return setFieldState(passwordInput, passwordFeedback, "");
    }

    // Confirm that both password fields contain exactly the same value.
    function validateConfirmation() {
        if (!confirmationInput.value) {
            return setFieldState(
                confirmationInput,
                confirmationFeedback,
                "Please confirm your password."
            );
        }

        if (confirmationInput.value !== passwordInput.value) {
            return setFieldState(
                confirmationInput,
                confirmationFeedback,
                "The passwords do not match."
            );
        }

        return setFieldState(confirmationInput, confirmationFeedback, "");
    }

    // Give feedback as each field is edited.
    emailInput.addEventListener("input", validateEmail);
    passwordInput.addEventListener("input", function () {
        validatePassword();

        // Recheck confirmation when changing a password that was already repeated.
        if (confirmationInput.value) {
            validateConfirmation();
        }
    });
    confirmationInput.addEventListener("input", validateConfirmation);

    // Stop invalid forms before they reach Flask; Flask repeats every check securely.
    registerForm.addEventListener("submit", function (event) {
        const emailIsValid = validateEmail();
        const passwordIsValid = validatePassword();
        const confirmationIsValid = validateConfirmation();

        if (!emailIsValid || !passwordIsValid || !confirmationIsValid) {
            event.preventDefault();
            registerForm.querySelector(".is-invalid")?.focus();
        }
    });
}
