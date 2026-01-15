async function load() {
  const res = await fetch("/players");
  const data = await res.json();
  const list = document.getElementById("list");
  list.innerHTML = "";
  data.forEach(p => {
    list.innerHTML += `<li>${p.name} - ${p.is_online ? "🟢" : "🔴"}</li>`;
  });
}
setInterval(load, 5000);
load();
