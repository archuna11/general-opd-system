# radiology_bp.py
import os
import requests
import time
import uuid
import threading
from datetime import datetime
from flask import Blueprint, request, render_template_string, send_from_directory, jsonify, redirect, url_for



# --- Simulation-only in-memory storage ---
import threading

SCAN_DB = {}                  # holds simulated scan requests
scan_lock = threading.Lock()  # ensures thread-safe access


radiology_bp = Blueprint("radiology", __name__, url_prefix="/radiology")  # <-- Added prefix

# --- Configuration & Global State ---
DEFAULT_HOST = "http://127.0.0.1:5000"  # target radiology server
os.makedirs("downloads", exist_ok=True)

REQUEST_QUEUE = []
queue_lock = threading.Lock()

# --- Helpers ---

def save_stream_to_file(resp, out_path, chunk_size=8192):
    with open(out_path, 'wb') as f:
        for chunk in resp.iter_content(chunk_size):
            if chunk:
                f.write(chunk)

def download_scan(host, scan_id, out_dir, uhid=None):
    url = f"{host.rstrip('/')}/api/scans/download/{scan_id}"
    try:
        with requests.get(url, stream=True, timeout=30) as r:
            if r.ok:
                disp = r.headers.get('Content-Disposition', '')
                if 'filename=' in disp:
                    fname = disp.split('filename=')[-1].strip(' "')
                else:
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    fname = f"{uhid or 'scan'}_{scan_id}_{ts}.dcm"
                out_path = os.path.join(out_dir, fname)
                save_stream_to_file(r, out_path)
                return fname
            else:
                return None
    except Exception as e:
        print(f"[download_scan] Error: {e}")
        return None

def poll_request_status(host, request_id, timeout_s, poll_interval_s, out_dir, uhid):
    status_url = f"{host.rstrip('/')}/api/request_status/{request_id}"
    started = time.time()
    while time.time() - started < timeout_s:
        try:
            r = requests.get(status_url, timeout=15)
            if r.ok:
                j = r.json()
                status = j.get('status')
                scan_id = j.get('scan_id')
                if status and status.lower() in ('attended', 'completed') and scan_id:
                    return download_scan(host, scan_id, out_dir, uhid)
        except requests.RequestException:
            pass
        time.sleep(poll_interval_s)
    return None

def perform_request(host, department, uhid, scan_type, body_part, poll_interval_s=3.0, timeout_s=300.0):
    url = f"{host.rstrip('/')}/api/v1/get_or_request_scan"
    payload = {
        "department_name": department,
        "uhid": uhid,
        "type_of_scan": scan_type,
        "body_part": body_part
    }
    headers = {'Accept': 'application/json, application/dicom, */*'}
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30, stream=True)
    except requests.RequestException as e:
        return None, f"Request error: {e}"

    if resp.status_code == 200:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"{uhid or 'scan'}_{ts}.dcm"
        out_path = os.path.join("downloads", fname)
        save_stream_to_file(resp, out_path)
        return fname, None

    if resp.status_code == 202:
        j = resp.json()
        request_id = j.get('request_id') or j.get('id')
        if not request_id:
            return None, f"Server returned 202 but no request_id was found: {j}"
        fname = poll_request_status(host, request_id, timeout_s, poll_interval_s, "downloads", uhid)
        if fname:
            return fname, None
        else:
            return None, "Polling timed out or the final download failed."

    return None, f"Server returned error {resp.status_code}: {resp.text[:400]}"

# --- Background Worker ---

def process_scan_request_worker(req_id, host, department, uhid, scan_type, body_part):
    print(f"[{req_id}] Starting background processing for UHID: {uhid}")
    dicom_file, error = perform_request(host, department, uhid, scan_type, body_part)
    with queue_lock:
        for req in REQUEST_QUEUE:
            if req['id'] == req_id:
                if error:
                    req['status'] = 'Failed'
                    req['error'] = error
                    print(f"[{req_id}] Processing failed: {error}")
                else:
                    req['status'] = 'Completed'
                    req['filename'] = dicom_file
                    print(f"[{req_id}] Processing completed. File: {dicom_file}")
                break

# --- Templates (use your existing HTML) ---
# Paste INDEX_HTML and VIEW_HTML here exactly as they are
# For brevity, assuming INDEX_HTML and VIEW_HTML are defined above


# --- Templates (index and view) with improved UI + toast notification ---

INDEX_HTML = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Submit Scan Request — DICOM App</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    /* subtle page background */
    body { background: radial-gradient(1200px 400px at 10% 10%, rgba(59,130,246,0.06), transparent),
                    radial-gradient(900px 300px at 90% 90%, rgba(99,102,241,0.035), transparent), #f3f4f6; }
    .glass { background: rgba(255,255,255,0.7); backdrop-filter: blur(6px); }
    .accent { background: linear-gradient(90deg,#4f46e5,#06b6d4); -webkit-background-clip: text; color: transparent;}
    .card-hover:hover { transform: none; box-shadow: 0 20px 40px rgba(15,23,42,0.08); }
    /* Toast */
    .toast { position: fixed; top: 24px; right: 24px; z-index: 50; min-width: 280px; max-width: 420px; }
    .toast-enter { transform: translateY(-12px) scale(0.98); opacity: 0; }
    .toast-visible { transform: translateY(0) scale(1); opacity: 1; transition: transform .28s cubic-bezier(.2,.9,.3,1), opacity .28s; }
    .toast-hide { transform: translateY(-12px) scale(0.98); opacity: 0; transition: transform .28s, opacity .28s; }
    .tiny { font-size: .85rem; }
  </style>
</head>
<body class="font-sans text-gray-800 min-h-screen">
  <!-- Header -->
  <header class="py-6">
    <div class="container mx-auto flex items-center justify-between px-4">
      <div class="flex items-center space-x-3">
        <div class="w-12 h-12 rounded-xl flex items-center justify-center bg-gradient-to-tr from-indigo-600 to-teal-400 text-white shadow-lg">
          <!-- simple mothership icon -->
          <svg xmlns="http://www.w3.org/2000/svg" class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 2v4M5 7l7 7 7-7M12 22v-6" />
          </svg>
        </div>
        <div>
          <div class="text-lg font-bold">DICOM Request App</div>
          <div class="text-xs text-gray-500">Request for a scan in seconds.</div>
        </div>
      </div>
      <nav class="space-x-4">
        <a href="/radiology/" class="px-3 py-2 rounded-md text-sm font-medium bg-white/60 glass hover:shadow-md">Submit</a>
        <a href="/radiology/view" class="px-3 py-2 rounded-md text-sm font-medium bg-white/60 glass hover:shadow-md">View Queue</a>
      </nav>
    </div>
  </header>

  <!-- Main -->
  <main class="container mx-auto px-4 pb-12">
    <div class="grid md:grid-cols-2 gap-8 items-start">
      <!-- Request form card -->
      <div class="glass rounded-2xl p-6 shadow-sm card-hover">
        <div class="flex justify-between items-center mb-4">
          <div>
            <h1 class="text-2xl font-bold text-gray-800">New Scan Request</h1>
          </div>
          <div class="text-right">
            <div class="text-sm text-gray-500">Dept</div>
            <div class="font-semibold">GENERALOP</div>
          </div>
        </div>

        <form method="POST" action="/radiology/" class="space-y-4">
          <input type="text" name="department" value="GENERALOP" class="hidden">
          <label class="block">
            <div class="text-xs text-gray-600 mb-1">Patient UHID</div>
            <input type="text" name="uhid" class="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-300" placeholder="UHID e.g. UHID77777" required>
          </label>

          <label class="block">
            <div class="text-xs text-gray-600 mb-1">Scan Type</div>
            <select name="scan_type" class="w-full border rounded-lg px-3 py-2 focus:outline-none" required>
              <option value="" disabled selected>Select Scan Type</option>
              <option value="CT">CT</option>
              <option value="MR">MR</option>
              <option value="XRAY">XRAY</option>
              <option value="US">ULTRASOUND</option>
              <option value="PET">PET</option>
            </select>
          </label>

          <label class="block">
            <div class="text-xs text-gray-600 mb-1">Body Part</div>
            <input type="text" name="body_part" class="w-full border rounded-lg px-3 py-2 focus:outline-none" placeholder="e.g. BRAIN" required oninput="this.value=this.value.toUpperCase()">
            <div class="text-xs text-gray-400 mt-1">Please spell the body part correctly for better matching.</div>
          </label>

          <div class="flex items-center space-x-3">
            <button type="submit" class="inline-flex items-center gap-2 bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg shadow">
              <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>
              Queue Request
            </button>
            <a href="/radiology/view" class="text-sm text-gray-600 hover:underline">Open queue</a>
          </div>
        </form>
      </div>

      <!-- Quick info / stats -->
      <div class="space-y-4">
        <div class="glass rounded-2xl p-6 shadow-sm card-hover">
          <div class="flex items-center justify-between mb-2">
            <h3 class="font-semibold text-gray-700">Quick Stats</h3>
            <div class="text-xs text-gray-500">Realtime (in-memory)</div>
          </div>
          <div class="grid grid-cols-3 gap-4 mt-3">
            <div class="p-3 rounded-lg bg-white/60 glass text-center">
              <div class="text-xs text-gray-500">Queued</div>
              <div id="stat-queued" class="text-2xl font-bold">0</div>
            </div>
            <div class="p-3 rounded-lg bg-white/60 glass text-center">
              <div class="text-xs text-gray-500">Completed</div>
              <div id="stat-completed" class="text-2xl font-bold">0</div>
            </div>
            <div class="p-3 rounded-lg bg-white/60 glass text-center">
              <div class="text-xs text-gray-500">Failed</div>
              <div id="stat-failed" class="text-2xl font-bold text-red-500">0</div>
            </div>
          </div>

          <div class="mt-4 text-xs text-gray-500">Note: Queue is in-memory and will reset on app restart.</div>
        </div>

        <div class="glass rounded-2xl p-6 shadow-sm card-hover">
          <h3 class="font-semibold text-gray-700 mb-2">Helpful</h3>
          <ul class="text-sm text-gray-600 space-y-2">
            <li>Open <a href="/radiology/view" class="text-indigo-600 hover:underline">View Queue</a> to monitor progress & view DICOMs.</li>
          </ul>
        </div>
      </div>
    </div>
  </main>

  <!-- Toast placeholder -->
  <div id="toast-root" class="toast"></div>

  <!-- Small script: fetch stats & show toast if created (via URL params) -->
  <script>
    async function fetchStats() {
      try {
        const res = await fetch('/radiology/api/queue_status');
        if (!res.ok) return;
        const q = await res.json();
        let queued = 0, completed = 0, failed = 0;
        for (const r of q) {
          if (r.status === 'Pending') queued++;
          else if (r.status === 'Completed') completed++;
          else if (r.status === 'Failed') failed++;
        }
        document.getElementById('stat-queued').textContent = queued;
        document.getElementById('stat-completed').textContent = completed;
        document.getElementById('stat-failed').textContent = failed;
      } catch (e) {
        // ignore
      }
    }

    // Show animated toast (auto-dismiss)
    function showToast(title, message, kind = 'success') {
      const root = document.getElementById('toast-root');
      const id = 't' + Math.random().toString(36).slice(2,9);
      const color = kind === 'error' ? 'bg-red-50 border-red-200' : 'bg-white border-indigo-100';
      const icon = kind === 'error' ? '<svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5 text-red-500" viewBox="0 0 20 20" fill="currentColor"><path d="M10 9a1 1 0 100 2 1 1 0 000-2z"/><path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.72-1.36 3.486 0l5.518 9.814A1 1 0 0116.518 15H3.482a1 1 0 01-.743-1.587L8.257 3.1z" clip-rule="evenodd"/></svg>'
                   : '<svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5 text-indigo-500" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-11.414V11a1 1 0 11-2 0V6.586L7.293 7.293A1 1 0 015.879 5.879l3-3A1 1 0 019.88 2.88L12 5l2.12-2.12a1 1 0 011.414 1.414L13.414 6H11z" clip-rule="evenodd"/></svg>';

      const el = document.createElement('div');
      el.id = id;
      el.className = `p-3 rounded-lg border ${color} shadow-sm toast-enter`;
      el.innerHTML = `<div class="flex items-start gap-3">
          <div class="pt-0.5">${icon}</div>
          <div>
            <div class="font-medium text-sm">${title}</div>
            <div class="text-xs text-gray-600 mt-1">${message}</div>
          </div>
          <div class="ml-4"><button class="text-gray-400 hover:text-gray-600 close-btn" aria-label="close">&times;</button></div>
        </div>`;
      root.appendChild(el);

      // animate in
      requestAnimationFrame(() => el.classList.add('toast-visible'));

      // close handler
      el.querySelector('.close-btn').addEventListener('click', () => {
        hide();
      });

      let hideTimeout = setTimeout(hide, 4200);
      function hide() {
        clearTimeout(hideTimeout);
        el.classList.remove('toast-visible');
        el.classList.add('toast-hide');
        setTimeout(() => el.remove(), 300);
      }
    }

    // If page has ?created_id=...&uhid=..., show toast once and remove params
    (function handleCreatedParam() {
      const params = new URLSearchParams(window.location.search);
      const created = params.get('created_id');
      const uhid = params.get('uhid');
      const scan = params.get('scan_type') || '';
      if (created && uhid) {
        showToast('Request created', `UHID ${uhid} queued ${scan ? '• ' + scan : ''}.`, 'success');
        // Remove query params to avoid re-showing on refresh
        params.delete('created_id'); params.delete('uhid'); params.delete('scan_type');
        const newUrl = window.location.pathname + (params.toString() ? '?' + params.toString() : '');
        window.history.replaceState({}, document.title, newUrl);
      }
    })();

    // initial stats + periodic refresh
    fetchStats();
    setInterval(fetchStats, 1800000);
  </script>
</body>
</html>
"""

VIEW_HTML = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Request Queue — DICOM App</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body { background: radial-gradient(1000px 300px at 15% 20%, rgba(99,102,241,0.03), transparent), #f8fafc; }
    .glass { background: rgba(255,255,255,0.8); backdrop-filter: blur(6px); }
    .card-hover:hover { transform: none; box-shadow: 0 14px 30px rgba(2,6,23,0.08); }
    .spinner { border: 3px solid rgba(0,0,0,0.06); width: 18px; height: 18px; border-radius: 999px; border-left-color: #2563eb; animation: spin 1s linear infinite;}
    @keyframes spin { to { transform: rotate(360deg); } }
    .timeline { border-left: 3px dashed rgba(99,102,241,0.12); padding-left: 16px; }
  </style>
</head>
<body class="font-sans text-gray-800 min-h-screen">
  <header class="py-6">
    <div class="container mx-auto flex items-center justify-between px-4">
      <div class="flex items-center space-x-3">
        <div class="w-12 h-12 rounded-xl flex items-center justify-center bg-gradient-to-tr from-indigo-600 to-teal-400 text-white shadow-lg">
          <svg xmlns="http://www.w3.org/2000/svg" class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 2v4M5 7l7 7 7-7M12 22v-6" />
          </svg>
        </div>
        <div>
          <div class="text-lg font-bold">DICOM Request App</div>
          <div class="text-xs text-gray-500">Queue monitor</div>
        </div>
      </div>
      <nav class="space-x-4">
        <a href="/radiology/" class="px-3 py-2 rounded-md text-sm font-medium bg-white/60 glass hover:shadow-md">Submit</a>
        <a href="/radiology/view" class="px-3 py-2 rounded-md text-sm font-medium bg-white/60 glass hover:shadow-md">View Queue</a>
      </nav>
    </div>
  </header>

  <main class="container mx-auto px-4 pb-12">
    <div class="bg-white/60 glass rounded-2xl p-6 shadow-sm">
      <h2 class="text-2xl font-bold mb-4">Request Queue</h2>
      <div class="flex justify-between items-center mb-4">
        <div class="text-sm text-gray-600">Realtime queue (in-memory)</div>
        <div class="text-sm"><button id="clear-queue" class="text-xs bg-red-50 text-red-600 px-3 py-1 rounded">Clear (dev)</button></div>
      </div>

      <div id="request-queue-container" class="space-y-3">
        <!-- populated by JS -->
      </div>
    </div>
  </main>

  <!-- Viewer modal -->
  <div id="viewer-modal" class="fixed inset-0 bg-black bg-opacity-60 flex items-center justify-center p-4 hidden">
    <div class="bg-white rounded-lg shadow-xl w-full max-w-3xl h-full max-h-[80vh] flex flex-col">
      <div class="p-3 border-b flex justify-between items-center">
        <h3 class="font-bold text-lg">DICOM Viewer</h3>
        <button id="close-modal-btn" class="text-gray-500 hover:text-gray-800 text-2xl">&times;</button>
      </div>
      <div id="dicomImage" class="w-full flex-grow bg-black"></div>
    </div>
  </div>

  <!-- Cornerstone libs -->
  <script src="https://unpkg.com/cornerstone-core@2.3.0/dist/cornerstone.js"></script>
  <script src="https://unpkg.com/dicom-parser@1.8.7/dist/dicomParser.js"></script>
  <script src="https://unpkg.com/cornerstone-wado-image-loader@3.1.2/dist/cornerstoneWADOImageLoader.js"></script>

  <script>
    // Cornerstone init
    try {
      cornerstoneWADOImageLoader.webWorkerManager.initialize({
        maxWebWorkers: navigator.hardwareConcurrency || 1,
        startWebWorkersOnDemand: true,
        taskConfiguration: { 'decodeTask': { initializeCodecsOnStartup: false, usePDFJS: false, strict: false } }
      });
      cornerstoneWADOImageLoader.external.cornerstone = cornerstone;
    } catch (e) { console.warn('cornerstone init failed', e); }

    const queueContainer = document.getElementById('request-queue-container');
    const modal = document.getElementById('viewer-modal');
    const dicomElement = document.getElementById('dicomImage');
    const closeModalBtn = document.getElementById('close-modal-btn');

    function renderQueue(queue) {
      if (!queue || queue.length === 0) {
        queueContainer.innerHTML = '<p class="text-center text-gray-500 py-8">No requests in the queue.</p>';
        return;
      }
      // Grouped timeline-like layout
      let html = '<div class="timeline">';
      for (const req of queue) {
        const when = new Date(req.timestamp).toLocaleString();
        const statusBadge = req.status === 'Pending' ? '<div class="text-xs text-blue-600">Pending</div>' :
                            req.status === 'Completed' ? '<div class="text-xs text-green-600">Completed</div>' :
                            '<div class="text-xs text-red-600">Failed</div>';
        const spinner = req.status === 'Pending' ? '<div class="spinner mr-2"></div>' : '';
        const viewBtn = (req.status === 'Completed' && req.filename) ? `<button class="view-dicom-btn bg-green-600 text-white px-3 py-1 rounded text-sm" data-filename="${req.filename}">View</button>` : '';
        const errMsg = req.error ? `<div class="text-xs text-red-500 mt-1">Err: ${req.error}</div>` : '';
        html += `
          <div class="mb-6 p-4 bg-white rounded-lg shadow-sm flex justify-between items-start card-hover">
            <div>
              <div class="flex items-center gap-3">
                ${spinner}
                <div>
                  <div class="font-medium">UHID: ${req.uhid} <span class="text-xs text-gray-400">• ${when}</span></div>
                  <div class="text-sm text-gray-600">${req.scan_type} — ${req.body_part}</div>
                  ${errMsg}
                </div>
              </div>
            </div>
            <div class="flex flex-col items-end gap-2">
              ${statusBadge}
              ${viewBtn}
            </div>
          </div>
        `;
      }
      html += '</div>';
      queueContainer.innerHTML = html;
    }

    async function fetchQueueStatus() {
      try {
        const res = await fetch('/radiology/api/queue_status');
        if (!res.ok) return;
        const q = await res.json();
        renderQueue(q);
      } catch (e) { console.error('fetchQueueStatus err', e); }
    }

    function enableCornerstone() {
      try { cornerstone.enable(dicomElement); } catch(e) {}
    }
    function disableCornerstone() {
      try { cornerstone.disable(dicomElement); } catch(e) {}
      dicomElement.innerHTML = '';
    }

    function showViewer(filename) {
      if (!filename) return;
      const imageId = `wadouri:${window.location.origin}/radiology/dicom/${encodeURIComponent(filename)}`;
      modal.classList.remove('hidden');
      enableCornerstone();
      cornerstone.loadAndCacheImage(imageId).then(function(image) {
        cornerstone.displayImage(dicomElement, image);
      }).catch(function(err) {
        dicomElement.innerHTML = '<div class="p-4 text-red-400">Failed to load DICOM image. Check console.</div>';
        console.error(err);
      });
    }

    closeModalBtn.addEventListener('click', () => {
      modal.classList.add('hidden');
      disableCornerstone();
    });

    // Delegated click for view-dicom buttons
    queueContainer.addEventListener('click', (ev) => {
      const btn = ev.target.closest('.view-dicom-btn');
      if (btn) {
        const filename = btn.dataset.filename;
        showViewer(filename);
      }
    });

    document.addEventListener('DOMContentLoaded', () => {
      fetchQueueStatus();
      setInterval(fetchQueueStatus, 1800000);

      // dev: clear queue
      document.getElementById('clear-queue').addEventListener('click', async () => {
        await fetch('/radiology/api/clear_queue', { method: 'POST' });
        fetchQueueStatus();
      });
    });
  </script>
</body>
</html>
"""


# --- Routes ---

# --- Templates (unchanged) ---
# INDEX_HTML and VIEW_HTML remain exactly as in your code, except JS API fetch paths updated below:

# Update JS fetch paths inside INDEX_HTML and VIEW_HTML:
# /api/queue_status --> /radiology/api/queue_status
# /api/clear_queue --> /radiology/api/clear_queue

# --- Routes ---



@radiology_bp.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        uhid = request.form.get("uhid")
        scan_type = request.form.get("scan_type")
        body_part = request.form.get("body_part")
        department = request.form.get("department", "ORTHOPEDICS")
        if not all([uhid, scan_type, body_part]):
            return "Missing form fields", 400

        new_request = {
            "id": str(uuid.uuid4()),
            "uhid": uhid,
            "scan_type": scan_type,
            "body_part": body_part,
            "status": "Pending",
            "filename": None,
            "error": None,
            "timestamp": datetime.now().isoformat()
        }

        with queue_lock:
            REQUEST_QUEUE.insert(0, new_request)

        thread = threading.Thread(
            target=process_scan_request_worker,
            args=(new_request['id'], DEFAULT_HOST, department, uhid, scan_type, body_part),
            daemon=True
        )
        thread.start()
        return redirect(url_for("radiology.index", created_id=new_request['id'], uhid=uhid, scan_type=scan_type))

    return render_template_string(INDEX_HTML)

@radiology_bp.route("/view", methods=["GET", "POST"])
def view_queue_page():
    return render_template_string(VIEW_HTML)

@radiology_bp.route("/api/queue_status")
def queue_status():
    with queue_lock:
        return jsonify(list(REQUEST_QUEUE))

@radiology_bp.route("/dicom/<path:filename>")
def serve_dicom(filename):
    return send_from_directory("downloads", filename, mimetype="application/octet-stream")

@radiology_bp.route("/api/clear_queue", methods=["POST"])
def api_clear_queue():
    with queue_lock:
        REQUEST_QUEUE.clear()
    return jsonify({"ok": True})


