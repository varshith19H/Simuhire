let questions = [];
let currentIndex = 0;
let transcript = "";
let recognition;

async function startVirtualInterview() {

    const res = await fetch("/api/generate_virtual_questions", {
        method: "POST"
    });

    const data = await res.json();
    questions = data.questions;

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    recognition = new SpeechRecognition();
    recognition.continuous = true;

    recognition.onresult = function(event) {
        for (let i = event.resultIndex; i < event.results.length; ++i) {
            transcript += event.results[i][0].transcript + " ";
        }
    };

    recognition.start();
    askNextQuestion();
}

function askNextQuestion() {

    if (currentIndex >= questions.length) {
        finishInterview();
        return;
    }

    alert("Avatar Question: " + questions[currentIndex]);

    setTimeout(() => {
        currentIndex++;
        askNextQuestion();
    }, 20000);
}

async function finishInterview() {
    recognition.stop();

    await fetch("/api/submit_virtual_interview", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ transcript: transcript })
    });

    alert("Virtual Interview Submitted");
    window.location.reload();
}