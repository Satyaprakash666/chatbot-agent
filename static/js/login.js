const container = document.getElementById('container');
const registerBtn = document.getElementById('register');
const loginBtn = document.getElementById('login');

let isOtpVerified = false;

// Utility: show alert
function showAlert(message, type = 'info') {
    const alertDiv = document.createElement('div');
    alertDiv.className = `custom-alert ${type}`;
    alertDiv.textContent = message;
    document.body.appendChild(alertDiv);

    setTimeout(() => {
        alertDiv.classList.add('hide');
        setTimeout(() => document.body.removeChild(alertDiv), 500);
    }, 3000);
}

// Switch between login/register forms
registerBtn.addEventListener('click', e => { e.preventDefault(); container.classList.add('active'); });
loginBtn.addEventListener('click', e => { e.preventDefault(); container.classList.remove('active'); });

document.addEventListener("DOMContentLoaded", () => {
    const emailInput = document.getElementById("email");
    const otpInput = document.getElementById("otp");
    const nameInput = document.getElementById("name");
    const signUpBtn = document.querySelector('.sign-up button:not(#sendOtp):not(#verifyOtp)');
    const signInBtn = document.querySelector('.sign-in button');
    const sendOtpBtn = document.getElementById("sendOtp");
    const verifyOtpBtn = document.getElementById("verifyOtp");
    const signUpPassword = document.querySelector('.sign-up input[type="password"]');
    const signInEmail = document.querySelector('.sign-in input[type="email"]');
    const signInPassword = document.querySelector('.sign-in input[type="password"]');
    const signUpForm = document.querySelector('.sign-up form');
    const signInForm = document.querySelector('.sign-in form');
    const resetPasswordLink = document.querySelector('.reset-password');

    // Prevent default form submission
    signUpForm.addEventListener('submit', e => e.preventDefault());
    signInForm.addEventListener('submit', e => e.preventDefault());

    signUpBtn.type = 'button';
    signInBtn.type = 'button';

    // -------------------- Send OTP --------------------
    sendOtpBtn.addEventListener("click", async () => {
        const email = emailInput.value.trim();
        const name = nameInput.value.trim();

        if (!email || !name) return showAlert("Please enter your name and email.", "warning");

        try {
            const response = await fetch("https://chatbot-agent-t22h.onrender.com/send-otp", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email, name })
            });
            const result = await response.json();

            response.ok ? showAlert(result.message, "success") : showAlert(result.error, "error");
        } catch (error) {
            console.error("OTP send error:", error);
            showAlert("An error occurred while sending OTP", "error");
        }
    });

    // -------------------- Verify OTP --------------------
    verifyOtpBtn.addEventListener("click", async () => {
        const email = emailInput.value.trim();
        const otp = otpInput.value.trim();

        if (!email || !otp) return showAlert("Please enter both email and OTP", "warning");

        try {
            const response = await fetch("https://chatbot-agent-t22h.onrender.com/verify-otp", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email, otp })
            });
            const result = await response.json();

            if (response.ok) {
                isOtpVerified = true;
                showAlert(result.message, "success");
            } else showAlert(result.error, "error");
        } catch (error) {
            console.error("OTP verify error:", error);
            showAlert("An error occurred while verifying OTP", "error");
        }
    });

    // -------------------- Sign Up --------------------
    signUpBtn.addEventListener("click", async () => {
        if (!isOtpVerified) return showAlert("Please verify your OTP first", "warning");

        const email = emailInput.value.trim();
        const password = signUpPassword.value;
        const name = nameInput.value.trim();

        if (!email || !password || !name) return showAlert("Please fill in all fields", "warning");

        try {
            const userCredential = await firebase.auth().createUserWithEmailAndPassword(email, password);
            await userCredential.user.updateProfile({ displayName: name });

            // Store user in backend DB
            await fetch('https://chatbot-agent-t22h.onrender.com/store_user', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, name })
            });

            showAlert("Registration successful!", "success");
            setTimeout(() => window.location.href = "https://chatbot-agent-t22h.onrender.com/home", 500);
        } catch (error) {
            let msg = "Registration failed: " + error.message;
            try {
                const parsed = JSON.parse(error.message);
                msg = parsed.error.message || msg;
            } catch {}
            showAlert(msg, "error");
        }
    });

    // -------------------- Sign In --------------------
    signInBtn.addEventListener("click", async () => {
        const email = signInEmail.value.trim();
        const password = signInPassword.value;

        if (!email || !password) return showAlert("Please fill in all fields", "warning");

        try {
            const userCredential = await firebase.auth().signInWithEmailAndPassword(email, password);
            showAlert("Sign in successful!", "success");
            setTimeout(() => window.location.href = "https://chatbot-agent-t22h.onrender.com//home", 500);
        } catch (error) {
            let msg = "Sign-in failed: " + error.message;
            try {
                const parsed = JSON.parse(error.message);
                msg = parsed.error.message || msg;
            } catch {}
            showAlert(msg, "error");
        }
    });

    // -------------------- Password Reset --------------------
    resetPasswordLink?.addEventListener('click', async e => {
        e.preventDefault();
        const email = signInEmail.value.trim();
        if (!email) return showAlert("Please enter your email first", "warning");

        try {
            await firebase.auth().sendPasswordResetEmail(email);
            showAlert("Password reset email sent! Check your inbox.", "success");
        } catch (error) {
            let msg = error.message;
            try {
                const parsed = JSON.parse(error.message);
                msg = parsed.error.message || msg;
            } catch {}
            showAlert(msg, "error");
        }
    });

    // -------------------- Auth State --------------------
    firebase.auth().onAuthStateChanged(user => {
        if (user) setTimeout(() => window.location.href = "https://chatbot-agent-t22h.onrender.com/home", 1000);
    });
});
