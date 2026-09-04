import webbrowser
from pathlib import Path

html = r"""<!DOCTYPE html>

<html lang="en">

<head>

<meta charset="UTF-8">

<meta name="viewport"
   content="width=device-width, initial-scale=1.0">

<title>
Offline AI Assistant — Installation Preview
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
        34px 38px 0;

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

    color: #8C9692;

    font-size: 11px;

    line-height: 1.5;
}

/* =========================
   CURRENT TASK
   ========================= */

.current-task {

    margin-top: 17px;

    display: flex;

    align-items: center;

    gap: 12px;

    padding:
        12px 14px;

    background:
        rgba(29, 138, 104, 0.08);

    border:
        1px solid
        rgba(29, 138, 104, 0.25);

    border-radius: 8px;
}

.spinner {

    width: 27px;

    height: 27px;

    border-radius: 50%;

    border:
        3px solid
        #29302E;

    border-top-color:
        #1D8A68;

    animation:
        spin 1s linear infinite;
}

@keyframes spin {

    to {

        transform:
            rotate(360deg);
    }
}

.task-title {

    color: #62C7A3;

    font-size: 11px;

    font-weight: 600;
}

.task-description {

    margin-top: 3px;

    color: #737D79;

    font-size: 9px;
}

/* =========================
   DYNAMIC INSIGHT
   ========================= */

.insight {

    margin-top: 10px;

    padding:
        10px 12px;

    background: #1C2221;

    border:
        1px solid
        #29302E;

    border-radius: 7px;
}

.insight-label {

    color: #737D79;

    font-size: 8px;

    text-transform: uppercase;

    letter-spacing: 0.5px;
}

.insight-text {

    margin-top: 4px;

    color: #A5AFAB;

    font-size: 10px;

    line-height: 1.4;
}

/* =========================
   PROGRESS
   ========================= */

.progress-section {

    margin-top: 16px;
}

.progress-header {

    display: flex;

    justify-content:
        space-between;

    align-items: center;
}

.progress-label {

    color: #A5AFAB;

    font-size: 10px;
}

.progress-percent {

    color: #62C7A3;

    font-size: 11px;

    font-weight: 600;
}

.progress-bar {

    margin-top: 7px;

    height: 7px;

    background: #29302E;

    border-radius: 5px;

    overflow: hidden;
}

.progress-fill {

    width: 42%;

    height: 100%;

    background: #1D8A68;

    border-radius: 5px;

    transition:
        width 0.5s ease;
}

/* =========================
   DOWNLOAD DETAILS
   ========================= */

.download-details {

    margin-top: 8px;

    display: flex;

    justify-content:
        space-between;

    color: #737D79;

    font-size: 9px;
}

/* =========================
   CURRENT FILE
   ========================= */

.current-file {

    margin-top: 11px;

    padding:
        9px 11px;

    background: #191F1E;

    border:
        1px solid
        #29302E;

    border-radius: 6px;

    display: flex;

    justify-content:
        space-between;

    align-items: center;
}

.file-name {

    color: #A5AFAB;

    font-size: 9px;
}

.file-status {

    color: #62C7A3;

    font-size: 9px;

    font-weight: 600;
}

/* =========================
   INSTALLATION STEPS
   ========================= */

.installation-steps {

    margin-top: 14px;

    display: flex;

    gap: 7px;
}

.install-step {

    flex: 1;

    padding:
        8px 6px;

    text-align: center;

    border:
        1px solid
        #29302E;

    background: #191F1E;

    border-radius: 6px;

    color: #59625F;

    font-size: 8px;
}

.install-step.done {

    color: #62C7A3;

    border-color:
        rgba(29, 138, 104, 0.35);
}

.install-step.active {

    color: #62C7A3;

    background:
        rgba(29, 138, 104, 0.08);

    border-color:
        rgba(29, 138, 104, 0.55);
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

.cancel {

    padding:
        9px 20px;

    border-radius: 6px;

    background:
        transparent;

    color: #A5AFAB;

    border:
        1px solid
        #343C39;

    font-family: inherit;

    font-size: 11px;

    cursor: pointer;
}

.cancel:hover {

    color: #D96565;

    border-color:
        rgba(217, 101, 101, 0.45);
}

</style>

</head>

<body>

<div class="page-title">

<h1>

Offline AI Assistant — Installation

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

<div class="step current">

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

100% Offline

<br>

Your data stays local

</div>

</div>

<!-- MAIN -->

<div class="content">

<div class="header">

<h2>

Installing Offline AI Assistant

</h2>

<p>

Please wait while the application and selected AI model
are being installed and verified. This process may take
several minutes depending on your storage and network speed.

</p>

</div>

<!-- CURRENT TASK -->

<div class="current-task">

<div class="spinner">

</div>

<div>

<div class="task-title"
     id="taskTitle">

Downloading AI Model

</div>

<div class="task-description"
     id="taskDescription">

Downloading Qwen 2.5 7B — Q4_K_M

</div>

</div>

</div>

<!-- DYNAMIC INSIGHT -->

<div class="insight">

<div class="insight-label">

About your selected model

</div>

<div class="insight-text"
     id="insightText">

Your selected model is optimized for local text
and code generation and can run with GPU acceleration.

</div>

</div>

<!-- PROGRESS -->

<div class="progress-section">

<div class="progress-header">

<div class="progress-label">

Overall Installation Progress

</div>

<div class="progress-percent"
     id="progressPercent">

42%

</div>

</div>

<div class="progress-bar">

<div class="progress-fill"
     id="progressFill">

</div>

</div>

<div class="download-details">

<span id="downloaded">

2.0 GB / 4.7 GB

</span>

<span id="speed">

8.4 MB/s

</span>

<span id="eta">

ETA 5 min

</span>

</div>

</div>

<!-- CURRENT FILE -->

<div class="current-file">

<div class="file-name"
     id="currentFile">

qwen2.5-7b-q4_k_m.gguf

</div>

<div class="file-status">

Downloading

</div>

</div>

<!-- INSTALLATION STEPS -->

<div class="installation-steps">

<div class="install-step done">

Application

</div>

<div class="install-step done">

Dependencies

</div>

<div class="install-step active">

AI Model

</div>

<div class="install-step">

Verification

</div>

<div class="install-step">

Finalization

</div>

</div>

<!-- BOTTOM -->

<div class="bottom">

<div class="version">

Offline AI Assistant · v1.2.0

</div>

<button class="cancel"
     id="cancelButton">

Cancel Installation

</button>

</div>

</div>

</div>

<script>

let progress = 42;

let cancelled = false;

const taskTitle =
    document.getElementById(
        "taskTitle"
    );

const taskDescription =
    document.getElementById(
        "taskDescription"
    );

const insightText =
    document.getElementById(
        "insightText"
    );

const progressFill =
    document.getElementById(
        "progressFill"
    );

const progressPercent =
    document.getElementById(
        "progressPercent"
    );

const downloaded =
    document.getElementById(
        "downloaded"
    );

const speed =
    document.getElementById(
        "speed"
    );

const eta =
    document.getElementById(
        "eta"
    );

const currentFile =
    document.getElementById(
        "currentFile"
    );

const cancelButton =
    document.getElementById(
        "cancelButton"
    );


const phases = [

    {
        start: 0,
        end: 20,

        title:
            "Installing Application",

        description:
            "Copying application files",

        insight:
            "The Offline AI Assistant application is being prepared for local use."
    },

    {
        start: 20,
        end: 35,

        title:
            "Installing Dependencies",

        description:
            "Preparing required local components",

        insight:
            "Required components are installed locally. No cloud service is required."
    },

    {
        start: 35,
        end: 80,

        title:
            "Downloading AI Model",

        description:
            "Downloading Qwen 2.5 7B — Q4_K_M",

        insight:
            "Your selected model is optimized for local text and code generation and can run with GPU acceleration."
    },

    {
        start: 80,
        end: 92,

        title:
            "Verifying AI Model",

        description:
            "Checking model integrity",

        insight:
            "The downloaded model is being verified to ensure the installation is complete and intact."
    },

    {
        start: 92,
        end: 100,

        title:
            "Finalizing Installation",

        description:
            "Preparing Offline AI Assistant",

        insight:
            "Your local AI environment is being finalized and prepared for first launch."
    }

];


function updateInstallation() {

    if (cancelled) {

        return;

    }


    progress += 0.35;


    if (progress >= 100) {

        progress = 100;

        taskTitle.textContent =
            "Installation Complete";

        taskDescription.textContent =
            "Offline AI Assistant is ready to use.";

        insightText.textContent =
            "Your assistant is installed locally and ready to run 100% offline.";

        progressFill.style.width =
            "100%";

        progressPercent.textContent =
            "100%";

        downloaded.textContent =
            "Installation complete";

        speed.textContent =
            "";

        eta.textContent =
            "Ready";

        currentFile.textContent =
            "Installation completed successfully";

        cancelButton.textContent =
            "Close";

        return;

    }


    progressFill.style.width =
        progress + "%";

    progressPercent.textContent =
        Math.floor(progress) + "%";


    let currentPhase =
        phases.find(
            phase =>
                progress >= phase.start &&
                progress < phase.end
        );


    if (currentPhase) {

        taskTitle.textContent =
            currentPhase.title;

        taskDescription.textContent =
            currentPhase.description;

        insightText.textContent =
            currentPhase.insight;

    }


    if (
        progress >= 35 &&
        progress < 80
    ) {

        let downloadedGB =
            (
                4.7 *
                (
                    progress - 35
                ) /
                45
            ).toFixed(1);

        downloaded.textContent =
            downloadedGB +
            " GB / 4.7 GB";

        speed.textContent =
            "8.4 MB/s";

        eta.textContent =
            "ETA " +
            Math.max(
                1,
                Math.floor(
                    (
                        80 - progress
                    ) /
                    4
                )
            ) +
            " min";

        currentFile.textContent =
            "qwen2.5-7b-q4_k_m.gguf";

    }

}


cancelButton.addEventListener(
    "click",
    function () {

        if (
            progress >= 100
        ) {

            window.close();

            return;

        }


        cancelled = true;

        taskTitle.textContent =
            "Installation Cancelled";

        taskDescription.textContent =
            "The installation was cancelled by the user.";

        insightText.textContent =
            "No further installation tasks will be performed.";

        cancelButton.textContent =
            "Close";

    }
);


setInterval(
    updateInstallation,
    500
);

</script>

</body>

</html>
"""

output = Path(
"installation_preview.html"
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
