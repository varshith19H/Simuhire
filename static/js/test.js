async function submitTest(testId){
    const answers = [];
    document.querySelectorAll(".question").forEach(q=>{
        const id = parseInt(q.dataset.id);
        const selected = q.querySelector("input:checked");
        answers.push({id:id, answer: selected ? parseInt(selected.value) : null});
    });

    const res = await fetch("/candidate/submit_test", {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body: JSON.stringify({test_id:testId, answers})
    });

    const data = await res.json();
    alert("Score: " + data.score + "/" + data.total);
    window.location.href="/candidate/dashboard";
}
