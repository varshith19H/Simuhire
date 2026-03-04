document.getElementById("applyForm")?.addEventListener("submit", async function(e){
    e.preventDefault();
    const formData = new FormData(this);

    const res = await fetch("/apply", {method:"POST", body: formData});
    const data = await res.json();

    alert(data.message || data.error);
});
