// static/js/main.js
const registration = document.getElementById("registration");
const quiz = document.getElementById("quiz");
const questionsContainer = document.getElementById("questionsContainer");
const resultDiv = document.getElementById("result");
let currentTestId = null;
let currentQuestions = [];

document.getElementById("candidateForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  resultDiv.innerHTML = "";
  const form = e.target;
  const fd = new FormData(form);
  // UI feedback
  const btn = form.querySelector(".btn");
  btn.disabled = true;
  btn.textContent = "Generating...";

  try {
    const resp = await fetch("/generate", { method: "POST", body: fd });
    const data = await resp.json();
    if (data.error) {
      alert("Error: " + (data.error || JSON.stringify(data)));
      btn.disabled = false;
      btn.textContent = "Start Interview";
      return;
    }

    currentTestId = data.test_id;
    currentQuestions = data.questions;

    // render questions
    registration.style.display = "none";
    quiz.style.display = "block";
    renderQuestions(currentQuestions);
  } catch (err) {
    alert("Network error: " + err);
    btn.disabled = false;
    btn.textContent = "Start Interview";
  }
});

function renderQuestions(questions) {
  questionsContainer.innerHTML = "";
  questions.forEach((q, idx) => {
    const qBox = document.createElement("div");
    qBox.className = "question-box";
    qBox.innerHTML = `
      <div class="q-number">Q${idx+1}</div>
      <div class="q-text">${q.question}</div>
      <div class="options" id="opts-${q.id}"></div>
    `;
    const optsDiv = qBox.querySelector(`#opts-${q.id}`);
    q.options.forEach((opt, i) => {
      const id = `q${q.id}_opt${i}`;
      const optHtml = document.createElement("label");
      optHtml.className = "option-label";
      optHtml.innerHTML = `
        <input type="radio" name="q${q.id}" value="${i}" id="${id}" />
        <span>${String.fromCharCode(65+i)}. ${opt}</span>
      `;
      optsDiv.appendChild(optHtml);
    });
    questionsContainer.appendChild(qBox);
  });
}

document.getElementById("submitAnswersBtn").addEventListener("click", async () => {
  // collect answers
  const answers = currentQuestions.map(q => {
    const radios = document.getElementsByName(`q${q.id}`);
    let chosen = null;
    for (let r of radios) {
      if (r.checked) { chosen = parseInt(r.value); break; }
    }
    return { id: q.id, answer: chosen };
  });

  // ensure all answered
  const anyUnanswered = answers.some(a => a.answer === null);
  if (anyUnanswered) {
    if (!confirm("Some questions are unanswered. Submit anyway?")) return;
  }

  resultDiv.innerHTML = "Submitting answers for evaluation...";
  try {
    const resp = await fetch("/submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ test_id: currentTestId, answers })
    });
    const data = await resp.json();
    if (data.error) {
      resultDiv.innerHTML = `<div class="error">Error: ${data.error}</div>`;
      return;
    }

    // show local score and AI score if available
    const local = data.local;
    const ai = data.ai;
    let html = `<h3>Results</h3>`;
    html += `<p><strong>Local Score:</strong> ${local.score} / ${local.total}</p>`;
    if (ai && ai.score !== undefined) {
      html += `<p><strong>AI Score:</strong> ${ai.score} / ${ai.total}</p>`;
    } else if (ai && ai.error) {
      html += `<p><strong>AI evaluation error:</strong> ${ai.error}</p>`;
    } else if (ai && ai.raw){
      html += `<pre>${ai.raw}</pre>`;
    }

    html += `<h4>Per-question</h4><ol>`;
    local.details.forEach(d => {
      const q = currentQuestions.find(x => String(x.id) === String(d.id));
      const chosenText = (d.chosen_index === null) ? "No answer" : q.options[d.chosen_index];
      const correctText = q.options[d.correct_index];
      html += `<li><div class="q-summary">${q.question}</div>
               <div>Selected: ${chosenText}</div>
               <div>Correct: ${correctText}</div>
               <div>Correct? ${d.correct ? "Yes" : "No"}</div>
               </li>`;
    });
    html += `</ol>`;
    // append AI detail if available
    if (ai && ai.details) {
      html += `<h4>AI Feedback</h4><pre>${JSON.stringify(ai.details, null, 2)}</pre>`;
    }
    resultDiv.innerHTML = html;

    // Optionally: disable further submissions
    document.getElementById("submitAnswersBtn").disabled = true;
  } catch (err) {
    resultDiv.innerHTML = "Network/error: " + err;
  }
});
