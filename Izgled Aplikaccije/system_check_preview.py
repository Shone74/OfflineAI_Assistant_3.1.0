import webbrowser
from pathlib import Path

html = r"""<!DOCTYPE html>

<html lang="en">

<head>

<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">

<title>Offline AI Assistant — System Check Preview</title>

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
   INSTALLER WINDOW
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
        38px
        42px
        0;

    display: flex;
    flex-direction: column;

    background: #151819;
}

.header h2 {
    margin: 0;

    font-size: 26px;

    font-weight: 500;
}

.header p {
    margin-top: 9px;

    max-width: 560px;

    color: #8C9692;

    font-size: 12px;

    line-height: 1.6;
}

/* =========================
   CHECK SUMMARY
   ========================= */

.summary {

    margin-top: 20px;

    padding: 14px 16px;

    display: flex;

    align-items: center;

    justify-content: space-between;

    background:
        rgba(29, 138, 104, 0.08);

    border:
        1px solid
        rgba(29, 138, 104, 0.22);

    border-radius: 8px;
}

.summary-left {
    display: flex;

    align-items: center;

    gap: 10px;
}

.summary-icon {

    width: 28px;
    height: 28px;

    border-radius: 50%;

    background: #245846;

    color: #7DE0B7;

    display: flex;

    align-items: center;
    justify-content: center;

    font-size: 13px;

    font-weight: 600;
}

.summary-title {

    font-size: 12px;

    font-weight: 600;

    color: #62C7A3;
}

.summary-description {

    margin-top: 3px;

    color: #737D79;

    font-size: 10px;
}

.summary-status {

    color: #62C7A3;

    font-size: 11px;

    font-weight: 600;
}

/* =========================
   CHECK GRID
   ========================= */

.check-grid {

    margin-top: 14px;

    display: grid;

    grid-template-columns:
        repeat(2, 1fr);

    gap: 8px;
}

.check-card {

    padding: 12px;

    display: flex;

    align-items: center;

    gap: 11px;

    background: #1C2221;

    border:
        1px solid
        #29302E;

    border-radius: 7px;
}

.check-icon {

    width: 30px;
    height: 30px;

    border-radius: 7px;

    display: flex;

    align-items: center;
    justify-content: center;

    font-size: 12px;

    font-weight: 600;
}

.check-icon.success {

    background:
        rgba(69, 184, 138, 0.12);

    color: #62C7A3;
}

.check-icon.warning {

    background:
        rgba(214, 162, 74, 0.12);

    color: #D6A24A;
}

.check-info {

    flex: 1;
}

.check-name {

    font-size: 11px;

    color: #A5AFAB;

    margin-bottom: 3px;
}

.check-value {

    font-size: 12px;

    color: #EDF3F0;

    font-weight: 600;
}

.check-status {

    font-size: 9px;

    font-weight: 600;

    text-transform: uppercase;

    letter-spacing: 0.4px;
}

.check-status.ready {

    color: #62C7A3;
}

.check-status.warning {

    color: #D6A24A;
}

/* =========================
   INFO MESSAGE
   ========================= */

.info {

    margin-top: 12px;

    padding: 11px 13px;

    background:
        rgba(214, 162, 74, 0.07);

    border:
        1px solid
        rgba(214, 162, 74, 0.18);

    border-radius: 7px;

    color: #AFA08A;

    font-size: 10px;

    line-height: 1.5;
}

/* =========================
   BOTTOM
   ========================= */

.bottom {

    margin-top: auto;

    padding:
        18px
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
Offline AI Assistant — System Check
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

<div class="step current">

<div class="step-icon">
2
</div>

<span>
System Check
</span>

</div>

<div class="step">

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

<!-- MAIN CONTENT -->

<div class="content">

<div class="header">

<h2>
System Check
</h2>

<p>

Before continuing, the installer will check your computer
to determine which AI models and features can run locally.

</p>

</div>

<!-- SUMMARY -->

<div class="summary">

<div class="summary-left">

<div class="summary-icon">
✓
</div>

<div>

<div class="summary-title">

System compatible

</div>

<div class="summary-description">

Your computer meets the minimum requirements
for Offline AI Assistant.

</div>

</div>

</div>

<div class="summary-status">

READY

</div>

</div>

<!-- CHECK GRID -->

<div class="check-grid">

<div class="check-card">

<div class="check-icon success">
CPU
</div>

<div class="check-info">

<div class="check-name">
Processor
</div>

<div class="check-value">
AMD Ryzen 7 5700X
</div>

</div>

<div class="check-status ready">
Ready
</div>

</div>

<div class="check-card">

<div class="check-icon success">
RAM
</div>

<div class="check-info">

<div class="check-name">
System Memory
</div>

<div class="check-value">
32 GB DDR4
</div>

</div>

<div class="check-status ready">
Ready
</div>

</div>

<div class="check-card">

<div class="check-icon success">
GPU
</div>

<div class="check-info">

<div class="check-name">
Graphics Processor
</div>

<div class="check-value">
RTX 3080 · 10 GB
</div>

</div>

<div class="check-status ready">
Ready
</div>

</div>

<div class="check-card">

<div class="check-icon success">
VRAM
</div>

<div class="check-info">

<div class="check-name">
GPU Memory
</div>

<div class="check-value">
10 GB Available
</div>

</div>

<div class="check-status ready">
Ready
</div>

</div>

<div class="check-card">

<div class="check-icon success">
OS
</div>

<div class="check-info">

<div class="check-name">
Operating System
</div>

<div class="check-value">
Windows 11 Pro
</div>

</div>

<div class="check-status ready">
Ready
</div>

</div>

<div class="check-card">

<div class="check-icon warning">
DISK
</div>

<div class="check-info">

<div class="check-name">
Available Storage
</div>

<div class="check-value">
18.2 GB Available
</div>

</div>

<div class="check-status warning">
Limited
</div>

</div>

</div>

<!-- INFO -->

<div class="info">

⚠ Storage space is sufficient for the basic installation,
but some larger AI models may require additional disk space.
You will be able to choose the model and installation location
on the following screens.

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

output = Path("system_check_preview.html")

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
