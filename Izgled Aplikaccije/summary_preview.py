import webbrowser
from pathlib import Path

html = r"""<!DOCTYPE html>

<html lang="en">

<head>

<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">

<title>Offline AI Assistant — Summary Preview</title>

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
        30px
        36px
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
    margin-top: 7px;

    color: #8C9692;

    font-size: 11px;

    line-height: 1.5;
}

/* =========================
   READY BANNER
   ========================= */

.ready-banner {

    margin-top: 13px;

    padding:
        10px
        13px;

    display: flex;

    align-items: center;

    gap: 10px;

    background:
        rgba(29, 138, 104, 0.08);

    border:
        1px solid
        rgba(29, 138, 104, 0.25);

    border-radius: 7px;
}

.ready-icon {

    width: 25px;
    height: 25px;

    border-radius: 50%;

    background: #245846;

    color: #7DE0B7;

    display: flex;

    align-items: center;
    justify-content: center;

    font-size: 12px;
}

.ready-title {

    color: #62C7A3;

    font-size: 11px;

    font-weight: 600;
}

.ready-text {

    margin-top: 2px;

    color: #737D79;

    font-size: 9px;
}

/* =========================
   SUMMARY GRID
   ========================= */

.summary-grid {

    margin-top: 12px;

    display: grid;

    grid-template-columns:
        repeat(2, 1fr);

    gap: 8px;
}

.card {

    padding: 11px 12px;

    background: #1C2221;

    border:
        1px solid
        #29302E;

    border-radius: 7px;
}

.card-title {

    color: #737D79;

    font-size: 9px;

    margin-bottom: 5px;
}

.card-value {

    color: #EDF3F0;

    font-size: 11px;

    font-weight: 600;
}

.card-detail {

    margin-top: 4px;

    color: #8C9692;

    font-size: 9px;

    line-height: 1.4;
}

/* =========================
   CAPABILITIES
   ========================= */

.capabilities {

    margin-top: 11px;

    padding:
        10px
        12px;

    background: #191F1E;

    border:
        1px solid
        #29302E;

    border-radius: 7px;
}

.capabilities-title {

    color: #737D79;

    font-size: 9px;

    margin-bottom: 7px;
}

.capability-list {

    display: flex;

    gap: 6px;

    flex-wrap: wrap;
}

.capability {

    padding:
        4px
        7px;

    border-radius: 4px;

    font-size: 8px;

    font-weight: 600;
}

.capability.active {

    background:
        rgba(29, 138, 104, 0.14);

    color: #62C7A3;
}

.capability.inactive {

    background:
        rgba(89, 98, 95, 0.12);

    color: #59625F;
}

/* =========================
   STORAGE SUMMARY
   ========================= */

.storage {

    margin-top: 10px;

    display: flex;

    justify-content:
        space-between;

    align-items: center;

    padding:
        10px
        12px;

    background:
        rgba(29, 138, 104, 0.06);

    border:
        1px solid
        rgba(29, 138, 104, 0.18);

    border-radius: 7px;
}

.storage-left {

    color: #8C9692;

    font-size: 9px;
}

.storage-left strong {

    color: #EDF3F0;
}

.storage-right {

    color: #62C7A3;

    font-size: 10px;

    font-weight: 600;
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

.install {

    background:
        #1D8A68;

    color: white;

    border:
        1px solid
        #1D8A68;

    font-weight: 600;
}

.install:hover {

    background:
        #249E78;
}

</style>

</head>

<body>

<div class="page-title">

<h1>
Offline AI Assistant — Installation Summary
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

<div class="step completed">

<div class="step-icon">
✓
</div>

<span>
AI Model
</span>

</div>

<div class="step completed">

<div class="step-icon">
✓
</div>

<span>
Locations
</span>

</div>

<div class="step current">

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
Ready to Install
</h2>

<p>

Please review your configuration before starting the installation.
You can go back to change any of the selected options.

</p>

</div>

<!-- READY -->

<div class="ready-banner">

<div class="ready-icon">
✓
</div>

<div>

<div class="ready-title">

Everything is ready

</div>

<div class="ready-text">

Your system meets the requirements and there is enough
space for the selected application and AI model.

</div>

</div>

</div>

<!-- SUMMARY GRID -->

<div class="summary-grid">

<div class="card">

<div class="card-title">

AI MODEL

</div>

<div class="card-value">

Qwen 2.5 7B — Q4_K_M

</div>

<div class="card-detail">

Recommended · ~4.7 GB · GPU Accelerated

</div>

</div>

<div class="card">

<div class="card-title">

APPLICATION

</div>

<div class="card-value">

C:\Program Files\Offline AI Assistant

</div>

<div class="card-detail">

Application and core components

</div>

</div>

<div class="card">

<div class="card-title">

AI MODELS

</div>

<div class="card-value">

D:\AI\Models

</div>

<div class="card-detail">

Model storage location · 742 GB free

</div>

</div>

<div class="card">

<div class="card-title">

HARDWARE

</div>

<div class="card-value">

RTX 3080 · 10 GB VRAM

</div>

<div class="card-detail">

Ryzen 7 5700X · 32 GB RAM

</div>

</div>

</div>

<!-- CAPABILITIES -->

<div class="capabilities">

<div class="capabilities-title">

MODEL CAPABILITIES

</div>

<div class="capability-list">

<div class="capability active">
✓ TEXT
</div>

<div class="capability active">
✓ CODE
</div>

<div class="capability active">
✓ DOCUMENTS
</div>

<div class="capability inactive">
✕ IMAGES
</div>

<div class="capability inactive">
✕ VIDEO
</div>

<div class="capability inactive">
✕ AUDIO
</div>

</div>

</div>

<!-- STORAGE -->

<div class="storage">

<div class="storage-left">

Installation size:

<strong>
~5.2 GB
</strong>

  ·  

Required model storage:

<strong>
~4.7 GB
</strong>

</div>

<div class="storage-right">

✓ Enough space

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

<button class="install">

Install

</button>

</div>

</div>

</div>

</div>

</body>

</html>
"""

output = Path("summary_preview.html")

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
