const API_BASE = "http://localhost:8000";
const WS_URL = "ws://localhost:8000/ws/stream";

const labels = [];
const chartData = {
  A: [],
  R: [],
  C: [],
};

const arcChart = new Chart(document.getElementById("arcChart"), {
  type: "line",
  data: {
    labels,
    datasets: [
      { label: "Arousal", data: chartData.A, borderColor: "#ef4444" },
      { label: "Regulation", data: chartData.R, borderColor: "#10b981" },
      { label: "Coherence", data: chartData.C, borderColor: "#3b82f6" },
    ],
  },
  options: {
    animation: false,
    scales: {
      y: { min: 0, max: 100 },
    },
  },
});

function pushPoint(arc) {
  const ts = new Date().toLocaleTimeString();
  labels.push(ts);
  chartData.A.push(arc.A);
  chartData.R.push(arc.R);
  chartData.C.push(arc.C);
  if (labels.length > 60) {
    labels.shift();
    chartData.A.shift();
    chartData.R.shift();
    chartData.C.shift();
  }
  arcChart.update();
}

function renderFeatures(features) {
  const table = document.getElementById("featureTable");
  table.innerHTML = Object.entries(features)
    .map(([k, v]) => `<tr><td>${k}</td><td>${Number(v).toFixed(4)}</td></tr>`)
    .join("");
}

function renderARC(payload) {
  if (!payload) return;
  document.getElementById("aVal").textContent = Number(payload.A).toFixed(2);
  document.getElementById("rVal").textContent = Number(payload.R).toFixed(2);
  document.getElementById("cVal").textContent = Number(payload.C).toFixed(2);
  document.getElementById("stateVal").textContent = payload.state;
  pushPoint(payload);
  renderFeatures(payload.features || {});
}

async function fetchProcessData() {
  const res = await fetch(`${API_BASE}/api/process-data`);
  if (!res.ok) return;
  const data = await res.json();
  renderARC(data);
}

async function sendRawBatch(batch) {
  await fetch(`${API_BASE}/api/ingest-data`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(batch),
  });
}

let ws = null;
function connectWebSocket() {
  ws = new WebSocket(WS_URL);
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "arc_update") {
      renderARC(msg.data);
    }
  };
}

let pollingTimer = null;
function startPolling() {
  if (pollingTimer) clearInterval(pollingTimer);
  fetchProcessData();
  pollingTimer = setInterval(fetchProcessData, 5000);
}

document.getElementById("connectWs").addEventListener("click", connectWebSocket);
document.getElementById("startPolling").addEventListener("click", startPolling);

// Hardware/source integration point:
// call window.pushRawSignals({ sampling_rate: 250, signals: { ecg: [...], ppg: [...], emg: [...] } })
window.pushRawSignals = async (batch) => {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(batch));
  } else {
    await sendRawBatch(batch);
  }
};

