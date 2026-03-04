let questions = [
    "Tell me about yourself.",
    "Why do you want this job?",
    "What are your strengths?"
];

let currentQuestion = 0;

async function startInterview() {

    // Start Camera
    const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
    document.getElementById("candidateVideo").srcObject = stream;

    askQuestion();
}

function askQuestion() {

    if (currentQuestion >= questions.length) {
        speak("Thank you for attending the interview. Goodbye.");
        return;
    }

    let question = questions[currentQuestion];
    document.getElementById("ai-text").innerText = question;

    speak(question);
    currentQuestion++;
}

function speak(text) {
    let speech = new SpeechSynthesisUtterance(text);
    speech.lang = "en-US";
    speech.onend = () => {
        startListening();
    };
    window.speechSynthesis.speak(speech);
}

function startListening() {

    const recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
    recognition.lang = "en-US";

    recognition.onresult = function(event) {
        let answer = event.results[0][0].transcript;
        console.log("Candidate Answer:", answer);

        setTimeout(() => {
            askQuestion();
        }, 2000);
    };

    recognition.start();
}