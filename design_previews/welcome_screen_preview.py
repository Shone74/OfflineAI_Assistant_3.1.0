import webbrowser
from pathlib import Path

html = r"""<!DOCTYPE html>

<html lang="en">

<head>

<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">

<title>Offline AI Assistant — Welcome Preview</title>

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
        42px
        48px
        0;

    display: flex;
    flex-direction: column;

    background: #151819;
}

/* =========================
   WELCOME
   ========================= */

.welcome {

    max-width: 580px;

    margin-top: 30px;
}

.welcome-icon {

    width: 70px;
    height: 70px;

    border-radius: 16px;

    background:
        rgba(29, 138, 104, 0.12);

    border:
        1px solid
        rgba(29, 138, 104, 0.25);

    display: flex;
    align-items: center;
    justify-content: center;

    color: #62C7A3;

    font-size: 26px;

    font-weight: 600;

    margin-bottom: 25px;
}

.welcome h2 {

    margin: 0;

    font-size: 29px;

    font-weight: 500;

    color: #EDF3F0;
}

.welcome-subtitle {

    margin-top: 12px;

    color: #A5AFAB;

    font-size: 14px;

    line-height: 1.7;
}

/* =========================
   PRIVACY CARD
   ========================= */

.privacy-card {

    margin-top: 28px;

    padding: 18px 20px;

    background: #1C2221;

    border:
        1px solid
        rgba(29, 138, 104, 0.25);

    border-radius: 9px;
}

.privacy-title {

    display: flex;

    align-items: center;

    gap: 9px;

    color: #62C7A3;

    font-size: 13px;

    font-weight: 600;
}

.privacy-icon {

    width: 22px;
    height: 22px;

    border-radius: 50%;

    background: #245846;

    display: flex;
    align-items: center;
    justify-content: center;

    font-size: 11px;
}

.privacy-text {

    margin-top: 9px;

    color: #8C9692;

    font-size: 11px;

    line-height: 1.6;
}

/* =========================
   FEATURES
   ========================= */

.features {

    margin-top: 18px;

    display: grid;

    grid-template-columns:
        repeat(2, 1fr);

    gap: 9px;
}

.feature {

    padding: 12px;

    background: #191F1E;

    border:
        1px solid
        #29302E;

    border-radius: 7px;
}

.feature-title {

    color: #EDF3F0;

    font-size: 11px;

    font-weight: 600;
}

.feature-text {

    margin-top: 4px;

    color: #737D79;

    font-size: 10px;

    line-height: 1.5;
}

/* =========================
   BOTTOM AREA
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

.cancel {

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
Offline AI Assistant — Welcome Screen
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

<div class="step current">

<div class="step-icon">
1
</div>

<span>
Welcome
</span>

</div>

<div class="step">

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

<div class="welcome">

<div class="welcome-icon">

AI

</div>

<h2>

Welcome to Offline AI Assistant

</h2>

<div class="welcome-subtitle">

This wizard will install Offline AI Assistant on your computer
and help you configure a local AI model based on your system
hardware and available storage.

</div>

<!-- PRIVACY -->

<div class="privacy-card">

<div class="privacy-title">

<div class="privacy-icon">

✓

</div>

100% Offline · Your data stays local

</div>

<div class="privacy-text">

After installation, Offline AI Assistant runs locally on your computer.
Your conversations, files and personal data remain on your device
and are not sent to external servers or cloud services.

</div>

</div>

<!-- FEATURES -->

<div class="features">

<div class="feature">

<div class="feature-title">

Local AI Processing

</div>

<div class="feature-text">

AI processing happens directly on your computer.

</div>

</div>

<div class="feature">

<div class="feature-title">

Private by Design

</div>

<div class="feature-text">

Your data remains under your control.

</div>

</div>

<div class="feature">

<div class="feature-title">

Hardware-Aware Setup

</div>

<div class="feature-text">

The installer will analyze your system configuration.

</div>

</div>

<div class="feature">

<div class="feature-title">

Model Recommendations

</div>

<div class="feature-text">

We will recommend models suitable for your hardware.

</div>

</div>

</div>

</div>

<!-- BOTTOM -->

<div class="bottom">

<div class="version">

Offline AI Assistant · v1.2.0

</div>

<div class="button-group">

<button class="cancel">

Cancel

</button>

<button class="next">

Next

</button>

</div>

</div>

</div>

</div>

</body>

</html>
"""

output = Path("welcome_screen_preview.html")

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
