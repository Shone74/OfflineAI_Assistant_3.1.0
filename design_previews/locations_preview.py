import webbrowser
from pathlib import Path

html = r"""<!DOCTYPE html>

<html lang="en">

<head>

<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">

<title>Offline AI Assistant — Locations Preview</title>

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

    max-width: 580px;

    color: #8C9692;

    font-size: 11px;

    line-height: 1.5;
}

/* =========================
   LOCATION CARDS
   ========================= */

.locations {

    margin-top: 18px;

    display: flex;

    flex-direction: column;

    gap: 11px;
}

.location-card {

    padding: 14px 16px;

    background: #1C2221;

    border:
        1px solid
        #29302E;

    border-radius: 8px;
}

.location-header {

    display: flex;

    align-items: center;

    justify-content: space-between;
}

.location-title {

    display: flex;

    align-items: center;

    gap: 9px;

    font-size: 12px;

    font-weight: 600;
}

.location-icon {

    width: 28px;
    height: 28px;

    border-radius: 7px;

    background:
        rgba(29, 138, 104, 0.12);

    color: #62C7A3;

    display: flex;

    align-items: center;

    justify-content: center;

    font-size: 12px;
}

.location-description {

    margin-top: 6px;

    color: #737D79;

    font-size: 9px;

    line-height: 1.4;
}

.path-row {

    margin-top: 10px;

    display: flex;

    gap: 7px;
}

.path-input {

    flex: 1;

    padding:
        8px
        10px;

    background: #151819;

    border:
        1px solid
        #343C39;

    border-radius: 5px;

    color: #A5AFAB;

    font-family:
        "Segoe UI",
        Arial,
        sans-serif;

    font-size: 10px;
}

.browse {

    padding:
        8px
        13px;

    background:
        #202624;

    color: #A5AFAB;

    border:
        1px solid
        #343C39;

    border-radius: 5px;

    font-family: inherit;

    font-size: 10px;

    cursor: pointer;
}

.browse:hover {

    background:
        #29302E;

    color:
        #EDF3F0;
}

/* =========================
   STORAGE INFO
   ========================= */

.storage-row {

    margin-top: 9px;

    display: flex;

    justify-content:
        space-between;

    align-items: center;

    font-size: 9px;
}

.storage-info {

    color: #737D79;
}

.storage-value {

    color: #62C7A3;

    font-weight: 600;
}

.storage-bar {

    margin-top: 6px;

    height: 4px;

    background:
        #29302E;

    border-radius: 5px;

    overflow: hidden;
}

.storage-fill {

    width: 32%;

    height: 100%;

    background:
        #1D8A68;
}

/* =========================
   MODEL STORAGE SUMMARY
   ========================= */

.summary {

    margin-top: 12px;

    padding:
        11px
        13px;

    display: flex;

    align-items: center;

    justify-content:
        space-between;

    background:
        rgba(29, 138, 104, 0.07);

    border:
        1px solid
        rgba(29, 138, 104, 0.20);

    border-radius: 7px;
}

.summary-left {

    color: #8C9692;

    font-size: 10px;
}

.summary-left strong {

    color: #EDF3F0;
}

.summary-right {

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
Offline AI Assistant — Installation Locations
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

<div class="step current">

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
Choose Installation Locations
</h2>

<p>

You can install the application and AI models in different locations.
This allows you to keep the application on your system drive
while storing large AI models on another drive.

</p>

</div>

<div class="locations">

<!-- APPLICATION -->

<div class="location-card">

<div class="location-header">

<div class="location-title">

<div class="location-icon">
APP
</div>

Application Installation

</div>

</div>

<div class="location-description">

The main Offline AI Assistant application and its components
will be installed in this location.

</div>

<div class="path-row">

<div class="path-input">

C:\Program Files\Offline AI Assistant

</div>

<button class="browse">

Browse

</button>

</div>

<div class="storage-row">

<div class="storage-info">

Available space on drive

</div>

<div class="storage-value">

184 GB free

</div>

</div>

<div class="storage-bar">

<div class="storage-fill">

</div>

</div>

</div>

<!-- MODELS -->

<div class="location-card">

<div class="location-header">

<div class="location-title">

<div class="location-icon">
AI
</div>

AI Models Location

</div>

</div>

<div class="location-description">

AI model files can require several gigabytes of storage.
You can store them on another drive with more available space.

</div>

<div class="path-row">

<div class="path-input">

D:\AI\Models

</div>

<button class="browse">

Browse

</button>

</div>

<div class="storage-row">

<div class="storage-info">

Available space on drive

</div>

<div class="storage-value">

742 GB free

</div>

</div>

<div class="storage-bar">

<div class="storage-fill">

</div>

</div>

</div>

</div>

<!-- SUMMARY -->

<div class="summary">

<div class="summary-left">

Selected model:

<strong>
Qwen 2.5 7B — Q4_K_M
</strong>

  ·  

Required model storage:

<strong>
~4.7 GB
</strong>

</div>

<div class="summary-right">

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

output = Path("locations_preview.html")

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
