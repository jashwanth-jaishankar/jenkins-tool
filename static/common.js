const $ = id => document.getElementById(id);
const el = target => typeof target === "string" ? $(target) : target;
function show(target, message, cls="") {
  const node = el(target);
  node.classList.remove("hidden", "error", "success");
  if (cls) node.classList.add(cls);
  node.textContent = message;
}
function fail(target, message) { show(target, message, "error"); }
function hide(target) { el(target).classList.add("hidden"); }

async function api(url, options={}) {
  const response = await fetch(url, {
    ...options,
    headers: {"Content-Type": "application/json", ...(options.headers || {})}
  });
  const raw = await response.text();
  let data;
  try { data = raw ? JSON.parse(raw) : {}; }
  catch { throw new Error(`Server returned a non-JSON response (HTTP ${response.status}). Check the Flask terminal for details.`); }
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function setOptions(select, values, placeholder) {
  select.innerHTML = "";
  const first = document.createElement("option");
  first.value = "";
  first.textContent = placeholder;
  select.appendChild(first);
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  }
}

function renderFiltered(select, all, filterText, placeholder, emptyText) {
  const previous = select.value;
  const needle = filterText.trim().toLowerCase();
  const matches = needle ? all.filter(v => v.toLowerCase().includes(needle)) : all;
  setOptions(select, matches, matches.length ? placeholder : emptyText);
  if (previous && matches.includes(previous)) {
    select.value = previous;
  } else if (needle && matches.length) {
    select.value = matches.find(v => v.toLowerCase() === needle) || matches[0];
  }
  return matches;
}
async function pollStatus(endpoint, queueUrl, target, onComplete) {
  const started = Date.now();
  let buildUrl = "";
  let errors = 0;
  const poll = async () => {
    try {
      let url = `${endpoint}?queue_url=${encodeURIComponent(queueUrl)}`;
      if (buildUrl) url += `&build_url=${encodeURIComponent(buildUrl)}`;
      const data = await api(url);
      errors = 0;
      if (data.url) buildUrl = data.url;
      show(target, data.message || data.state);
      if (["SUCCESS", "FAILURE", "ABORTED", "UNSTABLE", "CANCELLED"].includes(data.state)) {
        if (data.state === "SUCCESS") show(target, `${data.message}\n${data.url || ""}`, "success");
        else fail(target, `${data.message}\n${data.url || ""}`);
        onComplete(data);
        return;
      }
      setTimeout(poll, Date.now() - started > 60000 ? 5000 : 2000);
    } catch (e) {
      if (++errors < 3) {
        show(target, `Status check failed (${e.message}). Retrying...`);
        setTimeout(poll, 5000);
        return;
      }
      fail(target, e.message);
      onComplete({state: "ERROR"});
    }
  };
  poll();
}
