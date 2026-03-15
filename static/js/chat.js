document.addEventListener("DOMContentLoaded", () => {
    const auth = window.auth;

    const messagesContainer = document.getElementById("messages");
    const sendBtn = document.getElementById("send-btn");
    const input = document.getElementById("input");
    const attachBtn = document.getElementById("attach-btn");
    const fileInput = document.getElementById("file-input");
    const closeBtn = document.getElementById("close-btn");

    const accountBtn = document.getElementById("account-btn");
    const dropdown = document.getElementById("account-dropdown");
    const logoutBtn = document.getElementById("logout-btn");

    let currentUserEmail = null;

    function getTimeHM() {
    const now = new Date();
    const hours = now.getHours().toString().padStart(2, "0");
    const minutes = now.getMinutes().toString().padStart(2, "0");
    return `${hours}:${minutes}`;
}


    function parseMarkdown(text) {
        text = text.replace(/^# (.+)$/gm, '<h1>$1</h1>');
        text = text.replace(/^## (.+)$/gm, '<h2>$1</h2>');
        text = text.replace(/^### (.+)$/gm, '<h3>$1</h3>');
        text = text.replace(/^#### (.+)$/gm, '<h4>$1</h4>');

        text = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        text = text.replace(/\*([^*]+)\*/g, '<em>$1</em>');

        const listMatches = text.match(/(^\* .+(\n\* .+)*)/gm);
        if (listMatches) {
            listMatches.forEach(list => {
                const items = list.split('\n').map(line => '<li>' + line.replace(/^\* /, '') + '</li>').join('');
                text = text.replace(list, `<ul>${items}</ul>`);
            });
        }

        text = text.split(/\n\n+/).map(p => {
            p = p.replace(/\n/g, '<br>');
            if (!/^<h\d>/.test(p) && !/^<ul>/.test(p)) p = `<p>${p}</p>`;
            return p;
        }).join('');

        return text;
    }

    accountBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        dropdown.classList.toggle("hidden");
    });
    document.addEventListener("click", () => {
        dropdown.classList.add("hidden");
    });

    auth.onAuthStateChanged((user) => {
        if (user) {
            currentUserEmail = user.email;
            document.getElementById("user-display-name").innerText = user.displayName || "User";
            document.getElementById("user-email").innerText = user.email;
            document.getElementById("user-name-display").innerText =
                user.displayName?.split(" ")[0] || "Account";
        } else {
            window.location.href = "/";
        }
    });

    if (logoutBtn) {
        logoutBtn.addEventListener("click", () => {
            auth.signOut()
                .then(() => window.location.href = "/")
                .catch((err) => console.error("Logout error:", err));
        });
    }

    function scrollToBottom() {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    function removeElement(el) {
        if (el && el.parentNode) el.parentNode.removeChild(el);
    }

    function createMessageElement(text, isUser = false, metaText = getTimeHM()) {
        const wrapper = document.createElement('div');
        wrapper.classList.add('message', isUser ? 'user' : 'bot');

        const meta = document.createElement('div');
        meta.classList.add('meta');
        meta.innerHTML = `<span class="sender">${isUser ? 'You' : 'AI'}</span> · <time>${metaText}</time>`;

        const bubble = document.createElement('div');
        bubble.classList.add('bubble');
        bubble.innerHTML = isUser ? text : parseMarkdown(text);

        wrapper.appendChild(meta);
        wrapper.appendChild(bubble);
        messagesContainer.appendChild(wrapper);
        scrollToBottom();
    }

    function createAttachmentMessage(file) {
        const wrapper = document.createElement('div');
        wrapper.classList.add('message', 'user');

        wrapper.innerHTML = `
            <div class="meta"><span class="sender">You</span> · <time>${getTimeHM()}</time></div>
            <div class="attachment">
                <div class="file-info">
                    <div class="file-name">${file.name}</div>
                    <div class="file-meta">${(file.size / 1024 / 1024).toFixed(2)} MB — PDF</div>
                </div>
                <a href="${URL.createObjectURL(file)}" target="_blank" rel="noopener noreferrer">Open</a>
            </div>
        `;

        messagesContainer.appendChild(wrapper);
        scrollToBottom();
    }

    function showTypingIndicator() {
        const el = document.createElement('div');
        el.classList.add('message', 'bot', 'typing-indicator');
        el.innerHTML = `
            <div class="meta"><span class="sender">AI</span> · <time>${getTimeHM()}</time></div>
            <div class="bubble">
                <div class="typing"><span class="dot"></span><span class="dot"></span><span class="dot"></span></div>
            </div>
        `;
        messagesContainer.appendChild(el);
        scrollToBottom();
        return el;
    }

    function sendQuestionToServer(question) {
        if (!currentUserEmail) return;
        fetch("/ask", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email: currentUserEmail, question })
        }).then(res => res.json())
          .then(data => {
              if (data.response) createMessageElement(data.response, false);
              else createMessageElement("AI could not generate a response.", false);
          })
          .catch(err => createMessageElement("Server error. Try again.", false));
    }

    function sendMessage(e) {
        if (e) e.preventDefault();
        const text = input.value.trim();
        if (!text) return;

        createMessageElement(text, true);
        input.value = "";

        const typing = showTypingIndicator();
        setTimeout(() => {
            removeElement(typing);
            sendQuestionToServer(text);
        }, 500);
    }

    sendBtn.addEventListener("click", sendMessage);
    input.addEventListener("keydown", e => {
        if (e.key === "Enter") sendMessage(e);
    });

    attachBtn.addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", (e) => {
        const file = e.target.files?.[0];
        e.target.value = "";
        if (!file) return;

        const isPDF = file.type === "application/pdf" || /\.pdf$/i.test(file.name);
        if (!isPDF) return createMessageElement("Only PDF files allowed.", false);
        if (file.size > 25 * 1024 * 1024) return createMessageElement("Max size 25MB.", false);

        createAttachmentMessage(file);

        if (currentUserEmail) {
            const formData = new FormData();
            formData.append("email", currentUserEmail);
            formData.append("file", file);
            fetch("/pdf", {
                method: "POST",
                body: formData
            }).then(res => res.json())
              .then(data => console.log("PDF uploaded:", data))
              .catch(err => console.error("PDF upload error:", err));
        }

        const typing = showTypingIndicator();
        setTimeout(() => {
            removeElement(typing);
            createMessageElement(`PDF "${file.name}" uploaded. You can continue chatting.`, false);
        }, 500);
    });

    closeBtn.addEventListener("click", () => {
        if (!currentUserEmail) return;
        fetch("/close", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email: currentUserEmail })
        }).then(res => res.json())
          .then(data => console.log("Chat cleared:", data))
          .catch(err => console.error("Close error:", err));

        messagesContainer.innerHTML = "";
        createMessageElement("The chat has been cleared. You may continue again.", false, getTimeHM());
    });
});
