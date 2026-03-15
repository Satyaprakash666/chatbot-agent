// For Firebase JS SDK v7.20.0 and later, measurementId is optional
const rootUrl = 'https://chatbot-agent-t22h.onrender.com';
// const rootUrl = ''

const firebaseConfig = {
  apiKey: "AIzaSyCZnohyh3EPHHBCv88l96ddKFcFvHDv7Eo",
  authDomain: "chat-bot-cea01.firebaseapp.com",
  projectId: "chat-bot-cea01",
  storageBucket: "chat-bot-cea01.firebasestorage.app",
  messagingSenderId: "137917979431",
  appId: "1:137917979431:web:bfac72a9650341b2866702",
  measurementId: "G-EQN0SDN3FF"
};


firebase.initializeApp(firebaseConfig);
firebase.analytics();

const auth = firebase.auth();
window.auth = auth;

auth.setPersistence(firebase.auth.Auth.Persistence.LOCAL)
    .then(() => {
        console.log("Auth persistence set to LOCAL");
    })
    .catch((error) => {
        console.error("Error setting auth persistence:", error);
    });

console.log("Firebase initialized successfully");
console.log("Auth object:", auth); 
firebase.auth().onAuthStateChanged((user) => {
    const currentPath = window.location.pathname;

    if (user) {
        if (!currentPath.includes('home')) {
            // LINK HERE
            window.location.href = `${rootUrl}/home`;
        }
    } else {
        console.log("User is signed out");
        if (!currentPath.includes('')) {
            // LINK HERE
            window.location.href = `${rootUrl}/login`;
        }
    }
});
