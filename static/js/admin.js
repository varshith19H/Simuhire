async function accept(id){
    const res = await fetch(`/admin/accept/${id}`, {method:"POST"});
    const data = await res.json();
    alert(data.message);
    location.reload();
}

async function reject(id){
    const res = await fetch(`/admin/reject/${id}`, {method:"POST"});
    const data = await res.json();
    alert(data.message);
    location.reload();
}
