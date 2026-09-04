import webbrowser
from pathlib import Path

html = r"""<!DOCTYPE html>

<html lang="en">

<head>

<meta charset="UTF-8">

<meta name="viewport"
   content="width=device-width, initial-scale=1.0">

<title>
Offline AI Assistant — Installation Complete
</title>

<style>

* {
    box-sizing: border-box;
}

body {

    margin: 0;

    padding: 40px;

    background: #0D1010;

    color: #EDF3F0;

    font-family:
        "Segoe UI",
        Arial,
        sans-serif;
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

    border:
        1px solid
        #29302E;

    border-radius: 12px;

    box-shadow:
        0 25px 70px
        rgba(0, 0, 0, 0.55);
}

/* =========================
   SIDEBAR
   ========================= */

.sidebar {

    width: 245px;

    padding:
        28px 20px;

    background: #111516;

    display: flex;

    flex-direction: column;

    border-right:
        1px solid
        #202624;
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

    padding:
        9px 10px;

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
   MAIN
   ========================= */

.content {

    flex: 1;

    padding:
        32px 38px 0;

    display: flex;

    flex-direction: column;

    background: #151819;
}

/* =========================
   SUCCESS HEADER
   ========================= */

.success-header {

    text-align: center;

    padding-top: 3px;
}

.success-icon {

    width: 62px;

    height: 62px;

    margin:
        0 auto 13px;

    border-radius: 50%;

    background:
        rgba(29, 138, 104, 0.14);

    border:
        1px solid
        rgba(29, 138, 104, 0.35);

    display: flex;

    align-items: center;

    justify-content: center;

    color: #62C7A3;

    font-size: 28px;

    font-weight: 500;
}

.success-header h2 {

    margin: 0;

    font-size: 25px;

    font-weight: 500;
}

.success-header p {

    margin:
        7px auto 0;

    max-width: 520px;

    color: #8C9692;

    font-size: 11px;

    line-height: 1.5;
}

/* =========================
   OFFLINE BADGE
   ========================= */

.offline-badge {

    margin:
        13px auto 0;

    width: fit-content;

    padding:
        6px 11px;

    border-radius: 5px;

    background:
        rgba(29, 138, 104, 0.10);

    border:
        1px solid
        rgba(29, 138, 104, 0.25);

    color: #62C7A3;

    font-size: 9px;

    font-weight: 700;

    letter-spacing: 0.4px;
}

/* =========================
   SUMMARY
   ========================= */

.summary-grid {

    margin-top: 17px;

    display: grid;

    grid-template-columns:
        repeat(2, 1fr);

    gap: 8px;
}

.card {

    padding:
        10px 12px;

    background: #1C2221;

    border:
        1px solid
        #29302E;

    border-radius: 7px;
}

.card-title {

    color: #737D79;

    font-size: 8px;

    margin-bottom: 5px;
}

.card-value {

    color: #EDF3F0;

    font-size: 10px;

    font-weight: 600;
}

.card-detail {

    margin-top: 3px;

    color: #8C9692;

    font-size: 8px;
}

/* =========================
   MODEL STATUS
   ========================= */

.model-status {

    margin-top: 10px;

    padding:
        10px 12px;

    display: flex;

    justify-content:
        space-between;

    align-items: center;

    background:
        rgba(29, 138, 104, 0.07);

    border:
        1px solid
        rgba(29, 138, 104, 0.20);

    border-radius: 7px;
}

.model-info {

    color: #8C9692;

    font-size: 9px;
}

.model-info strong {

    color: #EDF3F0;
}

.status-ready {

    color: #62C7A3;

    font-size: 9px;

    font-weight: 600;
}

/* =========================
   PRIVACY MESSAGE
   ========================= */

.privacy {

    margin-top: 10px;

    padding:
        9px 12px;

    display: flex;

    align-items: center;

    gap: 9px;

    background: #191F1E;

    border:
        1px solid
        #29302E;

    border-radius: 7px;
}

.privacy-icon {

    color: #62C7A3;

    font-size: 13px;
}

.privacy-text {

    color: #8C9692;

    font-size: 9px;

    line-height: 1.4;
}

.privacy-text strong {

    color: #A5AFAB;
}

/* =========================
   BOTTOM
   ========================= */

.bottom {

    margin-top: auto;

    padding:
        16px 0;

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

    gap: 8px;
}

button {

    padding:
        9px 17px;

    border-radius: 6px;

    font-family: inherit;

    font-size: 10px;

    cursor: pointer;
}

.secondary {

    background:
        transparent;

    color: #A5AFAB;

    border:
        1px solid
        #343C39;
}

.secondary:hover {

    background:
        #202624;
}

.launch {

    background:
        #1D8A68;

    color: white;

    border:
        1px solid
        #1D8A68;

    font-weight: 600;
}

.launch:hover {

    background:
        #249E78;
}

</style>

</head>

<body>

<div class="page-title">

<h1>

Offline AI Assistant — Complete

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

<div class="step completed">

<div class="step-icon">

✓

</div>

<span>

Summary

</span>

</div>

<div class="step completed">

<div class="step-icon">

✓

</div>

<span>

Installation

</span>

</div>

<div class="step current">

<div class="step-icon">

✓

</div>

<span>

Complete

</span>

</div>

</div>

<div class="sidebar-footer">

100% Offline

<br>

Your data stays local

</div>

</div>

<!-- MAIN -->

<div class="content">

<!-- SUCCESS -->

<div class="success-header">

<div class="success-icon">

✓

</div>

<h2>

Installation Complete

</h2>

<p>

Offline AI Assistant has been successfully installed
and is ready to run on your computer.

</p>

<div class="offline-badge">

100% OFFLINE · YOUR DATA STAYS LOCAL

</div>

</div>

<!-- SUMMARY -->

<div class="summary-grid">

<div class="card">

<div class="card-title">

AI MODEL

</div>

<div class="card-value">

Qwen 2.5 7B — Q4_K_M

</div>

<div class="card-detail">

Ready · GPU Accelerated

</div>

</div>

<div class="card">

<div class="card-title">

APPLICATION LOCATION

</div>

<div class="card-value">

C:\Program Files\Offline AI Assistant

</div>

<div class="card-detail">

Application successfully installed

</div>

</div>

<div class="card">

<div class="card-title">

AI MODELS LOCATION

</div>

<div class="card-value">

D:\AI\Models

</div>

<div class="card-detail">

Model successfully downloaded

</div>

</div>

<div class="card">

<div class="card-title">

INSTALLATION VERSION

</div>

<div class="card-value">

Offline AI Assistant v1.2.0

</div>

<div class="card-detail">

Installation completed successfully

</div>

</div>

</div>

<!-- MODEL STATUS -->

<div class="model-status">

<div class="model-info">

Selected model:

<strong>
Qwen 2.5 7B — Q4_K_M
</strong>

  ·  

Model integrity verified

</div>

<div class="status-ready">

✓ READY

</div>

</div>

<!-- PRIVACY -->

<div class="privacy">

<div class="privacy-icon">

🔒

</div>

<div class="privacy-text">

<strong>

Your privacy is protected.

</strong>

Offline AI Assistant runs locally on your computer.
Your conversations and personal data remain on your device
and are not sent to external cloud services by the assistant.

</div>

</div>

<!-- BOTTOM -->

<div class="bottom">

<div class="version">

Offline AI Assistant · v1.2.0

</div>

<div class="button-group">

<button class="secondary"
     onclick="openFolder()">

Open Installation Folder

</button>

<button class="launch"
     onclick="launchAssistant()">

Launch Offline AI Assistant

</button>

</div>

</div>

</div>

</div>

<script>

function openFolder() {

    alert(
        "In the final installer this button will open the application installation folder."
    );

}


function launchAssistant() {

    alert(
        "In the final installer this button will launch Offline AI Assistant."
    );

}

</script>

</body>

</html>
"""

output = Path(
"complete_preview.html"
)

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
