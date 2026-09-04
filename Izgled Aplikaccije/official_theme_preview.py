import webbrowser
from pathlib import Path

html = r"""<!DOCTYPE html>

<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">

<title>Offline AI Assistant — Official Theme Preview</title>

<style>

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    padding: 40px;
    background: #0D1010;
    color: #EDF3F0;
    font-family: "Segoe UI", Arial, sans-serif;
}

h1 {
    text-align: center;
    font-size: 28px;
    font-weight: 500;
    margin: 0 0 8px;
}

.subtitle {
    text-align: center;
    color: #737D79;
    font-size: 14px;
    margin-bottom: 35px;
}

.preview {
    width: 900px;
    height: 600px;
    margin: 0 auto;
    display: flex;
    overflow: hidden;
    background: #151819;
    border: 1px solid #29302E;
    border-radius: 12px;
    box-shadow: 0 25px 70px rgba(0, 0, 0, 0.55);
}

/* =========================
   SIDEBAR
   ========================= */

.sidebar {
    width: 245px;
    padding: 28px 20px;
    background: #111516;
    display: flex;
    flex-direction: column;
    border-right: 1px solid #202624;
}

.brand {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 38px;
}

.logo {
    width: 42px;
    height: 42px;
    border-radius: 10px;
    background: #1D8A68;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 14px;
    font-weight: 700;
    color: #E8FFF6;
}

.brand-name {
    font-size: 14px;
    font-weight: 600;
}

.brand-subtitle {
    margin-top: 3px;
    font-size: 10px;
    color: #737D79;
}

.steps {
    display: flex;
    flex-direction: column;
    gap: 6px;
}

.step {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 9px 10px;
    border-radius: 7px;
    color: #737D79;
    font-size: 12px;
}

.step-icon {
    width: 22px;
    height: 22px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 10px;
    font-weight: 600;
    background: #202624;
}

.step.completed {
    color: #A5AFAB;
}

.step.completed .step-icon {
    background: #245846;
    color: #7DE0B7;
}

.step.current {
    color: #62C7A3;
    background: rgba(29, 138, 104, 0.12);
}

.step.current .step-icon {
    background: #1D8A68;
    color: white;
}

.sidebar-footer {
    margin-top: auto;
    color: #59625F;
    font-size: 10px;
    line-height: 1.6;
}

/* =========================
   MAIN CONTENT
   ========================= */

.content {
    flex: 1;
    padding: 35px 42px 0;
    display: flex;
    flex-direction: column;
    background: #151819;
}

.header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
}

.header h2 {
    margin: 0;
    font-size: 25px;
    font-weight: 500;
}

.header p {
    margin: 8px 0 0;
    color: #8C9692;
    font-size: 12px;
    line-height: 1.6;
    max-width: 500px;
}

.version {
    color: #737D79;
    font-size: 10px;
}

/* =========================
   HARDWARE SUMMARY
   ========================= */

.hardware {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 10px;
    margin-top: 25px;
}

.hardware-card {
    background: #1C2221;
    border: 1px solid #29302E;
    border-radius: 8px;
    padding: 13px;
}

.hardware-label {
    color: #737D79;
    font-size: 10px;
    margin-bottom: 6px;
}

.hardware-value {
    color: #EDF3F0;
    font-size: 12px;
    font-weight: 600;
}

/* =========================
   MODEL CARD
   ========================= */

.model-card {
    margin-top: 14px;
    padding: 16px;
    background: #1C2221;
    border: 1px solid rgba(29, 138, 104, 0.35);
    border-radius: 8px;
}

.model-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.model-title {
    font-size: 13px;
    font-weight: 600;
}

.recommended {
    padding: 4px 8px;
    border-radius: 5px;
    background: rgba(29, 138, 104, 0.15);
    color: #62C7A3;
    font-size: 9px;
    font-weight: 600;
}

.model-description {
    margin-top: 8px;
    color: #8C9692;
    font-size: 11px;
    line-height: 1.5;
}

/* =========================
   STATUS ROW
   ========================= */

.status-row {
    display: flex;
    gap: 10px;
    margin-top: 12px;
}

.status {
    flex: 1;
    padding: 10px;
    border-radius: 7px;
    font-size: 10px;
}

.status-success {
    background: rgba(69, 184, 138, 0.09);
    border: 1px solid rgba(69, 184, 138, 0.2);
    color: #62C7A3;
}

.status-warning {
    background: rgba(214, 162, 74, 0.09);
    border: 1px solid rgba(214, 162, 74, 0.2);
    color: #D6A24A;
}

.status-error {
    background: rgba(217, 101, 101, 0.09);
    border: 1px solid rgba(217, 101, 101, 0.2);
    color: #D96565;
}

/* =========================
   PROGRESS
   ========================= */

.progress-area {
    margin-top: auto;
}

.progress-header {
    display: flex;
    justify-content: space-between;
    margin-bottom: 7px;
    color: #737D79;
    font-size: 10px;
}

.progress {
    height: 5px;
    background: #29302E;
    border-radius: 10px;
    overflow: hidden;
}

.progress-fill {
    width: 62%;
    height: 100%;
    background: #1D8A68;
}

/* =========================
   BUTTONS
   ========================= */

.bottom {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 18px 0;
    margin-top: 15px;
    border-top: 1px solid #252B29;
}

.button-group {
    display: flex;
    gap: 9px;
}

button {
    padding: 8px 18px;
    border-radius: 6px;
    font-family: inherit;
    font-size: 11px;
    cursor: pointer;
}

.secondary {
    background: transparent;
    color: #A5AFAB;
    border: 1px solid #343C39;
}

.secondary:hover {
    background: #1C2221;
}

.primary {
    background: #1D8A68;
    color: white;
    border: 1px solid #1D8A68;
    font-weight: 600;
}

.primary:hover {
    background: #249E78;
}

.disabled {
    background: #202624;
    color: #59625F;
    border: 1px solid #29302E;
    cursor: default;
}

/* =========================
   LEGEND
   ========================= */

.legend {
    width: 900px;
    margin: 30px auto 0;
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 10px;
}

.legend-item {
    display: flex;
    align-items: center;
    gap: 8px;
    color: #8C9692;
    font-size: 11px;
}

.swatch {
    width: 18px;
    height: 18px;
    border-radius: 4px;
}

.graphite {
    background: #151819;
}

.sidebar-color {
    background: #111516;
}

.emerald {
    background: #1D8A68;
}

.success {
    background: #45B88A;
}

.warning {
    background: #D6A24A;
}

</style>

</head>

<body>

<h1>Offline AI Assistant</h1>

<div class="subtitle">
Official Theme — Graphite + Emerald
</div>

<div class="preview">

<div class="sidebar">

<div class="brand">

<div class="logo">
AI
</div>

<div>
<div class="brand-name">
Offline AI Assistant
</div>

<div class="brand-subtitle">
Installation Wizard
</div>
</div>

</div>

<div class="steps">

<div class="step completed">
<div class="step-icon">✓</div>
<span>Welcome</span>
</div>

<div class="step completed">
<div class="step-icon">✓</div>
<span>System Check</span>
</div>

<div class="step current">
<div class="step-icon">3</div>
<span>AI Model</span>
</div>

<div class="step">
<div class="step-icon">4</div>
<span>Locations</span>
</div>

<div class="step">
<div class="step-icon">5</div>
<span>Summary</span>
</div>

<div class="step">
<div class="step-icon">6</div>
<span>Installation</span>
</div>

<div class="step">
<div class="step-icon">7</div>
<span>Complete</span>
</div>

</div>

<div class="sidebar-footer">
100% Offline<br>
Your data stays local
</div>

</div>

<div class="content">

<div class="header">

<div>
<h2>Choose your AI Model</h2>

<p>
We analyzed your hardware configuration and selected a model
that provides the best balance between performance and resource usage.
</p>
</div>

<div class="version">
v1.2.0
</div>

</div>

<div class="hardware">

<div class="hardware-card">
<div class="hardware-label">CPU</div>
<div class="hardware-value">Ryzen 7 5700X</div>
</div>

<div class="hardware-card">
<div class="hardware-label">RAM</div>
<div class="hardware-value">32 GB</div>
</div>

<div class="hardware-card">
<div class="hardware-label">GPU</div>
<div class="hardware-value">RTX 3080 · 10 GB</div>
</div>

</div>

<div class="model-card">

<div class="model-header">

<div class="model-title">
Recommended Model — 7B / 8B
</div>

<div class="recommended">
RECOMMENDED
</div>

</div>

<div class="model-description">
Your hardware is well suited for a 7B–8B quantized model.
GPU acceleration is available and the selected model can run locally
without sending your data to external servers.
</div>

</div>

<div class="status-row">

<div class="status status-success">
✓ Hardware compatible
</div>

<div class="status status-warning">
! 8.4 GB storage required
</div>

<div class="status status-success">
✓ CUDA available
</div>

</div>

<div class="progress-area">

<div class="progress-header">

<span>Installation progress</span>

<span>62%</span>

</div>

<div class="progress">

<div class="progress-fill"></div>

</div>

<div class="bottom">

<button class="secondary">
Back
</button>

<div class="button-group">

<button class="disabled">
Cancel
</button>

<button class="primary">
Next
</button>

</div>

</div>

</div>

</div>

</div>

<div class="legend">

<div class="legend-item">
<div class="swatch graphite"></div>
Graphite
</div>

<div class="legend-item">
<div class="swatch sidebar-color"></div>
Sidebar
</div>

<div class="legend-item">
<div class="swatch emerald"></div>
Emerald
</div>

<div class="legend-item">
<div class="swatch success"></div>
Success
</div>

<div class="legend-item">
<div class="swatch warning"></div>
Warning
</div>

</div>

</body>
</html>
"""

output = Path("official_theme_preview.html")

output.write_text(
html,
encoding="utf-8",
)

webbrowser.open(
output.resolve().as_uri()
)

print(
f"Preview generated: {output.resolve()}"
)
