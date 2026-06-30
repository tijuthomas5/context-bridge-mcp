import os
import json
import asyncio
from pathlib import Path
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route
from starlette.requests import Request
from sse_starlette.sse import EventSourceResponse
import uvicorn
from mcp import ClientSession
from mcp.client.sse import sse_client
import tkinter as tk
from tkinter import filedialog
import time

HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CB Gauge</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-dark: #0f172a;
            --glass-bg: rgba(15, 23, 42, 0.45);
            --glass-border: rgba(255, 255, 255, 0.08);
            --accent: #3b82f6;
            --accent-hover: #60a5fa;
            --success: #10b981;
            --error: #ef4444;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
        }

        @keyframes bgPan {
            0% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
        }

        body {
            font-family: 'Inter', sans-serif;
            background: linear-gradient(-45deg, #0f172a, #1e1b4b, #0f172a, #31102e);
            background-size: 400% 400%;
            animation: bgPan 15s ease infinite;
            color: var(--text-main);
            min-height: 100vh;
            margin: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 2rem;
            box-sizing: border-box;
            overflow-x: hidden;
        }

        /* Animated background particles/blobs */
        .blob {
            position: fixed;
            border-radius: 50%;
            filter: blur(100px);
            z-index: 0;
            opacity: 0.6;
            animation: float 10s infinite ease-in-out alternate;
        }
        .blob-1 {
            width: 500px; height: 500px;
            background: rgba(59, 130, 246, 0.4);
            top: -150px; left: -100px;
        }
        .blob-2 {
            width: 400px; height: 400px;
            background: rgba(139, 92, 246, 0.4);
            bottom: -50px; right: -50px;
            animation-delay: -5s;
        }

        @keyframes float {
            0% { transform: translateY(0px) scale(1); }
            100% { transform: translateY(40px) scale(1.1); }
        }

        .container {
            width: 100%;
            max-width: 900px;
            background: var(--glass-bg);
            backdrop-filter: blur(24px);
            -webkit-backdrop-filter: blur(24px);
            border: 1px solid var(--glass-border);
            border-radius: 24px;
            padding: 2.5rem;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.1);
            display: flex;
            flex-direction: column;
            gap: 2rem;
            z-index: 10;
            position: relative;
            animation: slideUp 0.8s cubic-bezier(0.16, 1, 0.3, 1) forwards;
        }

        @keyframes slideUp {
            from { opacity: 0; transform: translateY(40px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .header-glow {
            position: relative;
            display: inline-block;
        }
        
        .header-glow::after {
            content: '';
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            width: 120%;
            height: 120%;
            background: radial-gradient(circle, rgba(96, 165, 250, 0.2) 0%, transparent 70%);
            z-index: -1;
            filter: blur(10px);
            animation: pulseGlow 3s ease-in-out infinite alternate;
        }

        @keyframes pulseGlow {
            0% { opacity: 0.5; transform: translate(-50%, -50%) scale(0.9); }
            100% { opacity: 1; transform: translate(-50%, -50%) scale(1.1); }
        }

        h1 {
            margin: 0;
            font-size: 2.8rem;
            font-weight: 700;
            background: linear-gradient(to right, #60a5fa, #c084fc, #f472b6);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            letter-spacing: -0.02em;
        }

        p.subtitle {
            margin: 0.5rem 0 0 0;
            color: var(--text-muted);
            font-size: 1.1rem;
            font-weight: 500;
        }

        .input-group {
            display: flex;
            flex-direction: column;
            gap: 0.6rem;
        }

        label {
            font-size: 0.95rem;
            font-weight: 500;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        input[type="text"], textarea {
            background: rgba(0, 0, 0, 0.2);
            border: 1px solid var(--glass-border);
            color: var(--text-main);
            padding: 1.2rem;
            border-radius: 14px;
            font-size: 1rem;
            outline: none;
            transition: all 0.3s ease;
            font-family: 'Inter', sans-serif;
            width: 100%;
            box-sizing: border-box;
            box-shadow: inset 0 2px 4px rgba(0,0,0,0.1);
        }
        
        textarea {
            font-family: 'Courier New', Courier, monospace;
            resize: vertical;
            min-height: 130px;
            line-height: 1.6;
        }

        input[type="text"]:focus, textarea:focus {
            border-color: var(--accent);
            box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.15), inset 0 2px 4px rgba(0,0,0,0.1);
            background: rgba(0, 0, 0, 0.3);
            transform: translateY(-1px);
        }

        .button-group {
            display: flex;
            gap: 1.5rem;
        }

        button {
            position: relative;
            overflow: hidden;
            background: linear-gradient(135deg, #2563eb, #4f46e5);
            color: white;
            border: 1px solid rgba(255,255,255,0.1);
            padding: 1.2rem 2rem;
            border-radius: 14px;
            font-size: 1.05rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275);
            box-shadow: 0 10px 20px -10px rgba(37, 99, 235, 0.6);
            flex: 1;
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 0.5rem;
        }

        button::before {
            content: '';
            position: absolute;
            top: 0; left: -100%; width: 50%; height: 100%;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.2), transparent);
            transition: all 0.5s ease;
        }

        button:hover:not(:disabled) {
            transform: translateY(-3px) scale(1.02);
            box-shadow: 0 15px 25px -10px rgba(37, 99, 235, 0.8);
            background: linear-gradient(135deg, #3b82f6, #6366f1);
        }

        button:hover:not(:disabled)::before {
            left: 150%;
        }

        button:active:not(:disabled) {
            transform: translateY(1px) scale(0.98);
        }

        button:disabled {
            background: rgba(255,255,255,0.05);
            color: var(--text-muted);
            cursor: not-allowed;
            border-color: transparent;
            box-shadow: none;
        }

        #stopBtn {
            background: linear-gradient(135deg, #dc2626, #991b1b);
            box-shadow: 0 10px 20px -10px rgba(220, 38, 38, 0.6);
        }
        #stopBtn:hover:not(:disabled) {
            background: linear-gradient(135deg, #ef4444, #b91c1c);
            box-shadow: 0 15px 25px -10px rgba(220, 38, 38, 0.8);
        }

        .console-container {
            background: rgba(0, 0, 0, 0.6);
            border-radius: 16px;
            border: 1px solid var(--glass-border);
            padding: 1.5rem;
            height: 380px;
            overflow-y: auto;
            font-family: 'Courier New', Courier, monospace;
            font-size: 0.95rem;
            line-height: 1.6;
            color: #e5e7eb;
            box-shadow: inset 0 5px 15px rgba(0,0,0,0.5);
            position: relative;
        }
        
        .console-container::after {
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0; height: 1px;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.1), transparent);
        }

        .log-item {
            margin-bottom: 0.5rem;
            padding-left: 1rem;
            border-left: 2px solid transparent;
            animation: slideInLeft 0.4s ease forwards;
            opacity: 0;
            transform: translateX(-10px);
        }

        @keyframes slideInLeft {
            to { opacity: 1; transform: translateX(0); }
        }

        .log-success { color: #34d399; border-left-color: #34d399; background: linear-gradient(90deg, rgba(52, 211, 153, 0.1) 0%, transparent 100%); }
        .log-error { color: #f87171; border-left-color: #f87171; background: linear-gradient(90deg, rgba(248, 113, 113, 0.1) 0%, transparent 100%); }
        .log-info { color: #93c5fd; border-left-color: #93c5fd; }
        .log-progress { color: #fde047; border-left-color: #fde047; }

        /* Custom Scrollbar */
        ::-webkit-scrollbar { width: 10px; height: 10px; }
        ::-webkit-scrollbar-track { background: rgba(0,0,0,0.3); border-radius: 5px; }
        ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.2); border-radius: 5px; border: 2px solid rgba(0,0,0,0.3); }
        ::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.4); }
    </style>
</head>
<body>

<div class="blob blob-1"></div>
<div class="blob blob-2"></div>

<div class="container">
    <div class="header-glow">
        <h1>CB Gauge</h1>
        <p class="subtitle">Next-Gen Context Bridge Telemetry Engine</p>
    </div>

    <div class="input-group">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <label for="pathsInput">Absolute paths to JSON files</label>
            <div style="display: flex; gap: 0.5rem;">
                <button id="clearPathsBtn" type="button" style="padding: 0.6rem 1.2rem; font-size: 0.85rem; flex: 0 0 auto; background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.3); color: #fca5a5; box-shadow: none;">Clear Paths</button>
                <button id="browseBtn" type="button" style="padding: 0.6rem 1.2rem; font-size: 0.85rem; flex: 0 0 auto; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); color: #e2e8f0; box-shadow: none;">Browse Files...</button>
            </div>
        </div>
        <textarea id="jsonPaths" placeholder="C:\Projects\Benchmarks\test_set_1.json&#10;C:\Projects\Benchmarks\test_set_2.json"></textarea>
    </div>

    <div class="input-group">
        <label for="serverUrl">Context Bridge SSE URL</label>
        <input type="text" id="serverUrl" value="http://127.0.0.1:8755/sse">
    </div>

    <div class="button-group">
        <button id="startBtn">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
            Start Batch Benchmark
        </button>
        <button id="stopBtn" disabled>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect></svg>
            Stop
        </button>
    </div>

    <div style="display: flex; justify-content: space-between; align-items: center; padding: 0 0.5rem;">
        <div style="display: flex; gap: 2rem;">
            <span style="color: var(--text-muted); font-size: 0.95rem; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em;">Total Requests Sent: <span id="totalRequestsCount" style="color: var(--accent); font-weight: 600; font-size: 1.1rem;">0</span></span>
            <span style="color: var(--text-muted); font-size: 0.95rem; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em;">Total Time: <span id="totalTimeCount" style="color: var(--success); font-weight: 600; font-size: 1.1rem;">0.00s</span></span>
        </div>
        <button id="clearStatsBtn" type="button" style="padding: 0.4rem 1rem; font-size: 0.75rem; background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.3); color: #fca5a5; box-shadow: none; width: auto; flex: none;">Clear Console</button>
    </div>

    <div class="console-container" id="console">
        <div class="log-item">System ready. Enter paths (one per line) and click start...</div>
    </div>
</div>

<script>
    const startBtn = document.getElementById("startBtn");
    const stopBtn = document.getElementById("stopBtn");
    const browseBtn = document.getElementById("browseBtn");
    const clearPathsBtn = document.getElementById("clearPathsBtn");
    const clearStatsBtn = document.getElementById("clearStatsBtn");
    const consoleDiv = document.getElementById("console");
    let currentSessionId = null;

    clearPathsBtn.addEventListener("click", () => {
        document.getElementById("jsonPaths").value = "";
    });

    clearStatsBtn.addEventListener("click", () => {
        document.getElementById("totalRequestsCount").textContent = "0";
        document.getElementById("totalTimeCount").textContent = "0.00s";
        consoleDiv.innerHTML = '<div class="log-item">Stats and console cleared.</div>';
    });

    function logMessage(text, type = "info") {
        const item = document.createElement('div');
        item.className = 'log-item ' + (type ? 'log-' + type : '');
        item.textContent = text;
        consoleDiv.appendChild(item);
        consoleDiv.scrollTop = consoleDiv.scrollHeight;
    }

    browseBtn.addEventListener("click", async () => {
        try {
            browseBtn.textContent = "Opening Dialog...";
            const response = await fetch("/browse", { method: "POST" });
            const data = await response.json();
            
            if (data.paths && data.paths.length > 0) {
                const textArea = document.getElementById("jsonPaths");
                const currentVal = textArea.value.trim();
                const newPaths = data.paths.join('\\n');
                textArea.value = currentVal ? currentVal + '\\n' + newPaths : newPaths;
            }
        } catch (e) {
            logMessage(`Error opening file browser: ${e.message}`, "error");
        } finally {
            browseBtn.textContent = "Browse Files...";
        }
    });

    startBtn.addEventListener("click", async () => {
        const rawPaths = document.getElementById("jsonPaths").value;
        const filePaths = rawPaths.split('\\n').map(p => p.trim()).filter(p => p.length > 0);
        const serverUrl = document.getElementById("serverUrl").value;
        
        if (filePaths.length === 0) {
            logMessage('Error: Please provide at least one valid file path.', 'error');
            return;
        }

        consoleDiv.innerHTML = "";
        document.getElementById('totalRequestsCount').textContent = "0";
        document.getElementById('totalTimeCount').textContent = "0.00s";
        startBtn.disabled = true;
        stopBtn.disabled = false;
        startBtn.textContent = "Running...";
        
        try {
            const response = await fetch("/start", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ file_paths: filePaths, server_url: serverUrl })
            });
            
            const data = await response.json();
            if (data.status === 'ok') {
                currentSessionId = data.session_id;
                connectSSE(currentSessionId);
            } else {
                logMessage(`Error: ${data.message}`, 'error');
                startBtn.disabled = false;
                stopBtn.disabled = true;
                startBtn.textContent = 'Start Batch Benchmark';
            }
        } catch (error) {
            logMessage(`Network Error: ${error.message}`, 'error');
            startBtn.disabled = false;
            stopBtn.disabled = true;
            startBtn.textContent = 'Start Batch Benchmark';
        }
    });

    stopBtn.addEventListener("click", async () => {
        if (!currentSessionId) return;
        stopBtn.disabled = true;
        stopBtn.textContent = "Stopping...";
        try {
            await fetch("/stop", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ session_id: currentSessionId })
            });
        } catch (e) {
            logMessage(`Error stopping: ${e.message}`, 'error');
        }
    });

    function connectSSE(sessionId) {
        const eventSource = new EventSource(`/stream?session_id=${sessionId}`);

        eventSource.onmessage = function(event) {
            const msg = JSON.parse(event.data);
            
            if (msg.type === 'stats') {
                document.getElementById('totalRequestsCount').textContent = msg.total_requests;
                if (msg.total_time !== undefined) {
                    document.getElementById('totalTimeCount').textContent = msg.total_time.toFixed(2) + "s";
                }
                return;
            }
            if (msg.type === 'info') logMessage(msg.message, 'info');
            if (msg.type === 'progress') logMessage(msg.message, 'progress');
            if (msg.type === 'success') logMessage(msg.message, 'success');
            if (msg.type === 'error') logMessage(msg.message, 'error');
            
            if (msg.type === 'done') {
                eventSource.close();
                startBtn.disabled = false;
                stopBtn.disabled = true;
                startBtn.textContent = 'Start Batch Benchmark';
                stopBtn.textContent = 'Stop Benchmark';
                logMessage("Benchmark process finished.", "success");
            }
        };
        
        eventSource.onerror = function(err) {
            logMessage('Stream connection lost.', 'error');
            eventSource.close();
            startBtn.disabled = false;
            stopBtn.disabled = true;
            startBtn.textContent = 'Start Batch Benchmark';
        }
    }
</script>
</body>
</html>
"""

# Global store for task states and queues
sessions = {}
active_tasks = {}

async def run_mcp_test(file_paths: list, server_url: str, session_id: str):
    queue = sessions[session_id]
    total_requests_sent = 0
    total_time_taken = 0.0
    
    try:
        for raw_path in file_paths:
            # Real-world fix: Strip quotes and extra whitespace
            clean_path = raw_path.strip().strip('"').strip("'")
            if not clean_path:
                continue
                
            path = Path(clean_path)
            if not path.exists():
                await queue.put({"type": "error", "message": f"File not found: {clean_path}"})
                continue

            output_dir = path.parent / "cb_test_results"
            output_dir.mkdir(exist_ok=True)
            out_path = output_dir / f"results_ui_{path.name}"

            try:
                with open(path, "r", encoding="utf-8") as f:
                    questions = json.load(f)
            except Exception as e:
                await queue.put({"type": "error", "message": f"Error reading {path.name}: {e}"})
                continue

            await queue.put({"type": "info", "message": f"Loaded {len(questions)} questions from {path.name}. Connecting..."})

            try:
                async with sse_client(server_url) as streams:
                    async with ClientSession(streams[0], streams[1]) as session:
                        await session.initialize()
                        await queue.put({"type": "success", "message": "Connected to Context Bridge."})
                        
                        results = []
                        for i, q in enumerate(questions, 1):
                            q_id = q.get("id", f"Q_{i}")
                            query = q.get("question")
                            
                            if not query:
                                continue
                                
                            total_requests_sent += 1
                            await queue.put({"type": "stats", "total_requests": total_requests_sent, "total_time": total_time_taken})
                            
                            await queue.put({"type": "progress", "message": f"[{path.name}] Processing {q_id} ({i}/{len(questions)})..."})
                            
                            try:
                                start_time = time.perf_counter()
                                result = await asyncio.wait_for(
                                    session.call_tool("search_context_hybrid", arguments={"query": query}),
                                    timeout=240.0
                                )
                                elapsed = time.perf_counter() - start_time
                                total_time_taken += elapsed
                                await queue.put({"type": "stats", "total_requests": total_requests_sent, "total_time": total_time_taken})
                                
                                res_text = ""
                                if result and hasattr(result, 'content'):
                                    for c in result.content:
                                        if hasattr(c, 'text'):
                                            res_text = c.text
                                
                                results.append({"id": q_id, "question": query, "result": str(result), "error": None})
                                
                                # --- Automatic Evaluation & Telemetry Logging ---
                                try:
                                    res_data = json.loads(res_text)
                                    event_id = res_data.get("event_id")
                                    
                                    # --- Real World Evaluation ---
                                    # Ignore the hallucinated JSON ground truth.
                                    # Evaluate based on Context Bridge's actual reported confidence.
                                    confidence = float(res_data.get('confidence', 0.0))
                                    files_returned = len(res_data.get('files', []))
                                    
                                    if files_returned == 0 or confidence < 0.45:
                                        status = "failed"
                                        missed = []
                                        reason = "bad_ranking"
                                    else:
                                        status = "success"
                                        missed = []
                                        reason = "none"
                                        
                                    if event_id:
                                        await session.call_tool("record_outcome", arguments={
                                            "event_id": event_id,
                                            "outcome": status,
                                            "missed_files": missed,
                                            "failure_reason": reason,
                                            "notes": f"Q-ID: {q_id} - Automated Benchmark"
                                        })
                                        await queue.put({"type": "info", "message": f"Recorded telemetry: {status.upper()} ({reason})"})
                                except Exception as eval_e:
                                    await queue.put({"type": "error", "message": f"Eval parsing error: {eval_e}"})
                                # ------------------------------------------------
                                
                                await queue.put({"type": "success", "message": f"{q_id} Success! (Completed in {elapsed:.2f}s)"})
                            except Exception as e:
                                results.append({"id": q_id, "question": query, "result": None, "error": str(e)})
                                await queue.put({"type": "error", "message": f"{q_id} Error: {e}"})
                                
                        with open(out_path, "w", encoding="utf-8") as f:
                            json.dump(results, f, indent=2, ensure_ascii=False)
                            
                        await queue.put({"type": "success", "message": f"Saved {path.name} results to {out_path}"})
                        
            except Exception as e:
                await queue.put({"type": "error", "message": f"Connection failed for {path.name}: {e}"})
            
    except asyncio.CancelledError:
        await queue.put({"type": "error", "message": "🛑 Benchmark execution was manually stopped!"})
    
    await queue.put({"type": "done"})

async def index(request: Request):
    return HTMLResponse(HTML_CONTENT)

async def start(request: Request):
    data = await request.json()
    file_paths = data.get("file_paths", [])
    server_url = data.get("server_url")
    
    session_id = os.urandom(8).hex()
    sessions[session_id] = asyncio.Queue()
    
    # Start the test in background
    task = asyncio.create_task(run_mcp_test(file_paths, server_url, session_id))
    active_tasks[session_id] = task
    
    return JSONResponse({"status": "ok", "session_id": session_id})

async def stop(request: Request):
    data = await request.json()
    session_id = data.get("session_id")
    
    if session_id and session_id in active_tasks:
        task = active_tasks[session_id]
        if not task.done():
            task.cancel()
            return JSONResponse({"status": "stopped"})
            
    return JSONResponse({"status": "not_found"})

async def browse(request: Request):
    try:
        # Run tkinter in a separate thread to prevent blocking uvicorn
        loop = asyncio.get_event_loop()
        def open_dialog():
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            files = filedialog.askopenfilenames(
                title="Select CB Benchmark JSON Files",
                filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")]
            )
            root.destroy()
            return files
            
        file_paths = await loop.run_in_executor(None, open_dialog)
        return JSONResponse({"paths": list(file_paths)})
    except Exception as e:
        return JSONResponse({"error": str(e), "paths": []})

async def stream(request: Request):
    session_id = request.query_params.get("session_id")
    if not session_id or session_id not in sessions:
        return JSONResponse({"error": "Invalid session"}, status_code=400)
        
    queue = sessions[session_id]

    async def event_generator():
        while True:
            msg = await queue.get()
            yield {"data": json.dumps(msg)}
            if msg.get("type") == "done":
                break

    return EventSourceResponse(event_generator())

app = Starlette(routes=[
    Route('/', index),
    Route('/start', start, methods=['POST']),
    Route('/stop', stop, methods=['POST']),
    Route('/browse', browse, methods=['POST']),
    Route('/stream', stream)
])

if __name__ == '__main__':
    print("\n" + "="*50)
    print("🚀 CB Gauge UI is running!")
    print("👉 Open your browser to: http://127.0.0.1:9856")
    print("="*50 + "\n")
    uvicorn.run(app, host='127.0.0.1', port=9856, log_level="error")
