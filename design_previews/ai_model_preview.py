import webbrowser
from pathlib import Path

html = r"""<!DOCTYPE html>

<html lang="en">

<head>

<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">

<title>Offline AI Assistant — AI Model Preview</title>

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

/* =========================
   PAGE HEADER
   ========================= */

.page-title {
    text-align: center;
    margin-bottom: 30px;
}

.page-title h1 {
    margin: 0;
    font-size: 27px;
    font-weight: 500;
}

.page-title p {
    margin-top: 8px;
    color: #737D79;
    font-size: 13px;
}

/* =========================
   INSTALLER
   ========================= */

.installer {
    width: 900px;
    height: 600px;
    margin: 0 auto;

    display: flex;

    overflow: hidden;

    background: #151819;

    border: 1px solid #29302E;

    border-radius: 12px;

    box-shadow:
        0 25px 70px rgba(0, 0, 0, 0.55);
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

/* =========================
   STEPS
   ========================= */

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

    color: #59625F;

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

    background:
        rgba(29, 138, 104, 0.12);
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

    padding:
        34px
        38px
        0;

    display: flex;
    flex-direction: column;

    background: #151819;
}

.header h2 {
    margin: 0;

    font-size: 25px;

    font-weight: 500;
}

.header p {
    margin-top: 8px;

    max-width: 560px;

    color: #8C9692;

    font-size: 11px;

    line-height: 1.5;
}

/* =========================
   HARDWARE SUMMARY
   ========================= */

.hardware-summary {

    margin-top: 15px;

    display: flex;

    gap: 8px;
}

.hardware-item {

    flex: 1;

    padding: 9px 11px;

    background: #1C2221;

    border:
        1px solid
        #29302E;

    border-radius: 6px;
}

.hardware-label {

    color: #737D79;

    font-size: 9px;

    margin-bottom: 4px;
}

.hardware-value {

    color: #EDF3F0;

    font-size: 10px;

    font-weight: 600;
}

/* =========================
   RECOMMENDED MODEL
   ========================= */

.recommended {

    margin-top: 12px;

    padding: 14px 16px;

    background:
        rgba(29, 138, 104, 0.08);

    border:
        1px solid
        rgba(29, 138, 104, 0.35);

    border-radius: 8px;
}

.recommended-header {

    display: flex;

    justify-content:
        space-between;

    align-items: center;
}

.model-name {

    font-size: 14px;

    font-weight: 600;

    color: #EDF3F0;
}

.badge {

    padding:
        4px
        8px;

    border-radius: 5px;

    background:
        rgba(29, 138, 104, 0.18);

    color: #62C7A3;

    font-size: 8px;

    font-weight: 700;

    letter-spacing: 0.5px;
}

.reason {

    margin-top: 7px;

    color: #8C9692;

    font-size: 10px;

    line-height: 1.5;
}

/* =========================
   MODEL STATS
   ========================= */

.model-stats {

    margin-top: 11px;

    display: grid;

    grid-template-columns:
        repeat(4, 1fr);

    gap: 7px;
}

.stat {

    padding: 8px;

    background: #191F1E;

    border:
        1px solid
        #29302E;

    border-radius: 6px;
}

.stat-label {

    color: #737D79;

    font-size: 8px;
}

.stat-value {

    margin-top: 4px;

    color: #A5AFAB;

    font-size: 10px;

    font-weight: 600;
}

/* =========================
   MODEL OPTIONS
   ========================= */

.options-title {

    margin-top: 13px;

    color: #A5AFAB;

    font-size: 10px;

    font-weight: 600;
}

.model-options {

    margin-top: 7px;

    display: grid;

    grid-template-columns:
        repeat(3, 1fr);

    gap: 7px;
}

.option {

    padding: 9px;

    background: #1C2221;

    border:
        1px solid
        #29302E;

    border-radius: 6px;

    cursor: pointer;
}

.option:hover {

    border-color:
        #1D8A68;
}

.option.selected {

    background:
        rgba(29, 138, 104, 0.09);

    border-color:
        rgba(29, 138, 104, 0.55);
}

.option-name {

    font-size: 10px;

    color: #EDF3F0;

    font-weight: 600;
}

.option-status {

    margin-top: 4px;

    font-size: 8px;

    color: #62C7A3;
}

.option-compatible {

    color: #D6A24A;
}

/* =========================
   BOTTOM
   ========================= */

.bottom {

    margin-top: auto;

    padding:
        16px
        0;

    border-top:
        1px solid
        #252B29;

    display: flex;

    justify-content:
        space-between;

    align-items: center;
}

.version {

    color: #59625F;

    font-size: 10px;
}

.button-group {

    display: flex;

    gap: 9px;
}

button {

    padding:
        9px
        20px;

    border-radius: 6px;

    font-family: inherit;

    font-size: 11px;

    cursor: pointer;
}

.back {

    background:
        transparent;

    color: #A5AFAB;

    border:
        1px solid
        #343C39;
}

.next {

    background:
        #1D8A68;

    color: white;

    border:
        1px solid
        #1D8A68;

    font-weight: 600;
}

.next:hover {

    background:
        #249E78;
}

</style>

</head>

<body>

<div class="page-title">

<h1>
Offline AI Assistant — AI Model Selection
</h1>

<p>
Official Theme · Graphite + Emerald
</p>

</div>

<div class="installer">

<!-- SIDEBAR -->

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

<div class="step-icon">
✓
</div>

<span>
Welcome
</span>

</div>

<div class="step completed">

<div class="step-icon">
✓
</div>

<span>
System Check
</span>

</div>

<div class="step current">

<div class="step-icon">
3
</div>

<span>
AI Model
</span>

</div>

<div class="step">

<div class="step-icon">
4
</div>

<span>
Locations
</span>

</div>

<div class="step">

<div class="step-icon">
5
</div>

<span>
Summary
</span>

</div>

<div class="step">

<div class="step-icon">
6
</div>

<span>
Installation
</span>

</div>

<div class="step">

<div class="step-icon">
7
</div>

<span>
Complete
</span>

</div>

</div>

<div class="sidebar-footer">

100% Offline <br>

Your data stays local

</div>

</div>

<!-- MAIN -->

<div class="content">

<div class="header">

<h2>
Choose your AI Model
</h2>

<p>

Based on your hardware configuration, we recommend the model
that provides the best balance between quality, speed and resource usage.

</p>

</div>

<!-- HARDWARE -->

<div class="hardware-summary">

<div class="hardware-item">

<div class="hardware-label">
CPU
</div>

<div class="hardware-value">
Ryzen 7 5700X
</div>

</div>

<div class="hardware-item">

<div class="hardware-label">
RAM
</div>

<div class="hardware-value">
32 GB
</div>

</div>

<div class="hardware-item">

<div class="hardware-label">
GPU
</div>

<div class="hardware-value">
RTX 3080
</div>

</div>

<div class="hardware-item">

<div class="hardware-label">
VRAM
</div>

<div class="hardware-value">
10 GB
</div>

</div>

</div>

<!-- RECOMMENDED -->

<div class="recommended">

<div class="recommended-header">

<div class="model-name">

Qwen 2.5 7B — Q4_K_M

</div>

<div class="badge">

RECOMMENDED

</div>

</div>

<div class="reason">

Recommended for your system because it offers a strong balance
of response quality, local performance and VRAM usage.
GPU acceleration is available on your RTX 3080.

</div>

<div class="model-stats">

<div class="stat">

<div class="stat-label">
Model Size
</div>

<div class="stat-value">
~4.7 GB
</div>

</div>

<div class="stat">

<div class="stat-label">
VRAM Usage
</div>

<div class="stat-value">
~6.5 GB
</div>

</div>

<div class="stat">

<div class="stat-label">
Performance
</div>

<div class="stat-value">
Excellent
</div>

</div>

<div class="stat">

<div class="stat-label">
GPU Acceleration
</div>

<div class="stat-value">
Available
</div>

</div>

</div>

</div>

<!-- OPTIONS -->

<div class="options-title">

Other available models

</div>

<div class="model-options">

<div class="option selected">

<div class="option-name">

Qwen 2.5 7B

</div>

<div class="option-status">

Recommended

</div>

</div>

<div class="option">

<div class="option-name">

Llama 3.1 8B

</div>

<div class="option-status">

Compatible

</div>

</div>

<div class="option">

<div class="option-name">

Qwen 2.5 14B

</div>

<div class="option-status option-compatible">

Limited

</div>

</div>

<div class="option">

<div class="option-name">

Small / Fast Model

</div>

<div class="option-status">

Recommended

</div>

</div>

<div class="option">

<div class="option-name">

Large Quality Model

</div>

<div class="option-status option-compatible">

Limited

</div>

</div>

<div class="option">

<div class="option-name">

User Defined

</div>

<div class="option-status">

Custom

</div>

</div>

</div>

<!-- BOTTOM -->

<div class="bottom">

<div class="version">

Offline AI Assistant · v1.2.0

</div>

<div class="button-group">

<button class="back">

Back

</button>

<button class="next">

Continue

</button>

</div>

</div>

</div>

</div>

</body>

</html>
"""

output = Path("ai_model_preview.html")

output.write_text(
html,
encoding="utf-8"
)

webbrowser.open(
output.resolve().as_uri()
)

print(
f"Preview generated: {output.resolve()}"
)
