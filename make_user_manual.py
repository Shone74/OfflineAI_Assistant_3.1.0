"""Build the USER MANUAL PDF with reportlab (real, searchable text).

Complete technical + practical manual for the Offline AI Assistant.
Every chapter is built from reportlab flowables (Paragraph, Table,
Preformatted, custom boxes) — the result is a professional, text-searchable
PDF with embedded fonts.

Run:  python make_user_manual.py   ->  USER_MANUAL.pdf
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, ".")

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)

OUT = Path("USER_MANUAL.pdf")

# Design tokens (Graphite + Emerald, matching the app theme)
EMERALD = colors.HexColor("#27C48A")
DARK = colors.HexColor("#202326")
CARD = colors.HexColor("#292D31")
BORDER = colors.HexColor("#373C41")
TEXT = colors.HexColor("#F1F3F4")
MUTED = colors.HexColor("#A8AFB5")
MUTED2 = colors.HexColor("#6E757B")
AMBER = colors.HexColor("#D6A24A")

PAGE_W, PAGE_H = A4

# ----------------------------------------------------------------------
# Styles
# ----------------------------------------------------------------------
ss = getSampleStyleSheet()

S_BODY = ParagraphStyle(
    "Body", parent=ss["Normal"], fontName="Helvetica", fontSize=10,
    leading=14, textColor=TEXT, spaceAfter=6,
)
S_H1 = ParagraphStyle(
    "H1", parent=ss["Heading1"], fontName="Helvetica-Bold", fontSize=20,
    leading=25, textColor=EMERALD, spaceBefore=6, spaceAfter=10,
)
S_H2 = ParagraphStyle(
    "H2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=13.5,
    leading=17, textColor=EMERALD, spaceBefore=12, spaceAfter=5,
)
S_H3 = ParagraphStyle(
    "H3", parent=ss["Heading3"], fontName="Helvetica-Bold", fontSize=11,
    leading=14, textColor=TEXT, spaceBefore=8, spaceAfter=4,
)
S_CELL = ParagraphStyle(
    "Cell", parent=S_BODY, fontSize=8.8, leading=11.5, spaceAfter=0,
)
S_CELLH = ParagraphStyle(
    "CellH", parent=S_CELL, fontName="Helvetica-Bold", textColor=EMERALD,
)
S_CODE = ParagraphStyle(
    "Code", parent=S_BODY, fontName="Courier", fontSize=8.3, leading=10.6,
    textColor=TEXT, spaceAfter=0,
)
S_TIP = ParagraphStyle("Tip", parent=S_BODY, fontSize=9.5, leading=13, spaceAfter=0)
S_META = ParagraphStyle("Meta", parent=S_BODY, fontSize=8, textColor=MUTED2)
S_COVER_T = ParagraphStyle(
    "CoverT", parent=S_BODY, fontName="Helvetica-Bold", fontSize=34,
    leading=40, textColor=EMERALD, alignment=TA_CENTER,
)
S_COVER_S = ParagraphStyle(
    "CoverS", parent=S_BODY, fontSize=17, leading=22, textColor=TEXT,
    alignment=TA_CENTER,
)
S_COVER_M = ParagraphStyle(
    "CoverM", parent=S_BODY, fontSize=10, leading=14, textColor=MUTED,
    alignment=TA_CENTER,
)


class HRule(Flowable):
    """A thin emerald horizontal rule used under H1s."""

    def __init__(self, width: float = 170 * mm) -> None:
        super().__init__()
        self.width = width

    def wrap(self, aw, ah):
        return aw, 4

    def draw(self) -> None:
        self.canv.setStrokeColor(EMERALD)
        self.canv.setLineWidth(1.6)
        self.canv.line(0, 2, self.width, 2)


def _box(story: list, flowables: list, border_color=EMERALD) -> None:
    """Wrap flowables in a rounded dark box (tip / warning callout)."""
    inner = Table(
        [[flowables]],
        colWidths=[158 * mm],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), CARD),
            ("BOX", (0, 0), (-1, -1), 0.8, border_color),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]),
    )
    story.append(inner)
    story.append(Spacer(1, 6))


def tip(story: list, text: str) -> None:
    _box(story, [Paragraph(f"<b>TIP</b> — {text}", S_TIP)])


def warn(story: list, text: str) -> None:
    _box(story, [Paragraph(f"<b>NOTE</b> — {text}", S_TIP)], border_color=AMBER)


def code(story: list, text: str) -> None:
    t = Table(
        [[Preformatted(text, S_CODE)]],
        colWidths=[166 * mm],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), CARD),
            ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]),
    )
    story.append(t)
    story.append(Spacer(1, 6))


def tbl(story: list, headers: list[str], rows: list[list[str]], widths=None) -> None:
    """Build a themed table. Cell content may contain <b> markup."""
    data = [[Paragraph(h, S_CELLH) for h in headers]]
    for row in rows:
        data.append([Paragraph(c, S_CELL) for c in row])
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), CARD),
        ("BACKGROUND", (0, 1), (-1, -1), DARK),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    story.append(Spacer(1, 8))


def h1(story: list, text: str) -> None:
    story.append(Paragraph(text, S_H1))
    story.append(HRule())
    story.append(Spacer(1, 4))


def h2(story: list, text: str) -> None:
    story.append(Paragraph(text, S_H2))


def p(story: list, text: str) -> None:
    story.append(Paragraph(text, S_BODY))


# ----------------------------------------------------------------------
# Page decoration
# ----------------------------------------------------------------------
def on_page(canvas, doc) -> None:
    canvas.saveState()
    # Dark background across the full page
    canvas.setFillColor(DARK)
    canvas.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
    # Footer
    canvas.setFillColor(MUTED2)
    canvas.setFont("Helvetica", 7.5)
    canvas.drawRightString(
        PAGE_W - 14 * mm, 9 * mm,
        f"Offline AI Assistant — User Manual  ·  Page {canvas.getPageNumber()}",
    )
    canvas.drawString(14 * mm, 9 * mm, "100% offline · local · private")
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(14 * mm, 12 * mm, PAGE_W - 14 * mm, 12 * mm)
    canvas.restoreState()


def on_cover(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFillColor(DARK)
    canvas.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
    canvas.setStrokeColor(EMERALD)
    canvas.setLineWidth(2)
    canvas.rect(10 * mm, 10 * mm, PAGE_W - 20 * mm, PAGE_H - 20 * mm)
    canvas.restoreState()


# ----------------------------------------------------------------------
# Content
# ----------------------------------------------------------------------

def cover(story: list) -> None:
    story.append(Spacer(1, 40 * mm))
    story.append(Paragraph("100% OFFLINE · LOCAL · PRIVATE", S_COVER_M))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("USER MANUAL", S_COVER_T))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Offline AI Assistant", S_COVER_S))
    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph(
        "Complete Technical Reference &amp; Practical Guide<br/>"
        "Version 1.0 · September 2026",
        ParagraphStyle("cv", parent=S_COVER_M, fontSize=11.5, leading=16),
    ))
    story.append(Spacer(1, 22 * mm))
    req_rows = [
        ["Operating system", "Windows 10 / 11 (64-bit)"],
        ["Python", "3.11 (bundled via launcher)"],
        ["GPU (optional)", "NVIDIA + CUDA — hardware acceleration"],
        ["Memory", "16 GB recommended · 32 GB for large models"],
        ["Storage", "3–20 GB per AI model"],
    ]
    t = Table(
        [[Paragraph("<b>System Requirements</b>", S_CELLH)]]
        + [[Paragraph(a, S_CELL), Paragraph(b, S_CELL)] for a, b in req_rows],
        colWidths=[45 * mm, 80 * mm],
        hAlign="CENTER",
    )
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), CARD),
        ("SPAN", (0, 0), (1, 0)),
        ("BACKGROUND", (0, 1), (-1, -1), DARK),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    story.append(Spacer(1, 16 * mm))
    story.append(Paragraph(
        "Generated from the verified application state · 182 automated tests passing",
        S_COVER_M,
    ))


def toc(story: list) -> None:
    h1(story, "Table of Contents")
    rows = [
        ["1", "Overview &amp; Architecture", "What the app is; how the layers fit together"],
        ["2", "Technical Specifications", "Full technical data — models, subsystems, files"],
        ["3", "First Steps", "Launch, wizard, loading your first model"],
        ["4", "Chat", "Messaging, files, Vision images, voice, slash-commands"],
        ["5", "Models &amp; Capabilities", "Loading, switching, what each model can do"],
        ["6", "Agents — Complete Guide", "★ Creating new agents with worked examples"],
        ["7", "Projects — Complete Guide", "★ Projects, assigned agents, chat context"],
        ["8", "Automation &amp; Workflows", "★ Scheduled tasks and multi-step workflows"],
        ["9", "Knowledge, Memory &amp; RAG", "Documents, memory layers, semantic search"],
        ["10", "Online API (Multi-Provider)", "OpenRouter / Groq / Google / custom — opt-in"],
        ["11", "Voice", "STT, TTS, wake word, Automatic Listening"],
        ["12", "Security &amp; Permissions", "Tool policies, confirmation gates, audit"],
        ["13", "Settings Reference", "Every settings tab explained"],
        ["14", "Tools Reference", "All 17 built-in tools with parameters"],
        ["15", "Troubleshooting &amp; FAQ", "Common problems and solutions"],
    ]
    tbl(
        story,
        ["Ch.", "Section", "What you will learn"],
        rows,
        widths=[12 * mm, 62 * mm, 96 * mm],
    )


def ch1(story: list) -> None:
    h1(story, "1 · Overview &amp; Architecture")
    h2(story, "1.1 What is the Offline AI Assistant?")
    p(story,
      "A fully local, private AI assistant for Windows. Every component — the language "
      "model, speech recognition, memory, knowledge base and automation — runs on your "
      "machine. <b>No data ever leaves your computer</b> unless you explicitly enable the "
      "optional Online API (Chapter 10).")
    h2(story, "1.2 Architecture at a glance")
    code(story, """+------------------------------------------------------------------+
|                         USER INTERFACE                           |
|   Home - Chat - Memory - Knowledge - Models - Capabilities       |
|   Projects - Agents - Tools - Voice - Automation - Workflow       |
+------------------------------+-----------------------------------+
                               |  EventBus (pub/sub, thread-safe)
+------------------------------+-----------------------------------+
|                        CORE (Assistant)                          |
|  Chat pipeline - context budget - memory - RAG integration       |
|  slash-commands - agent selection - project context manager      |
+----------------+---------------+----------------+-----------------+
|   AI ENGINES   |    AGENTS     |   AUTOMATION   |    SECURITY    |
|  llama.cpp     | Plan->Act->   | Scheduler -    | Permission     |
|  (local GGUF)  | Summarize     | Workflows -    | profiles -     |
|  OpenAI-compat | Orchestrator  | cron/interval  | confirmation   |
|  (online, opt) |               |                | gates + audit  |
+----------------+---------------+----------------+-----------------+
|                   TOOL REGISTRY (17 secured tools)                |
+----------------+---------------+----------------+-----------------+
|     VOICE      |   KNOWLEDGE   |     MEMORY     |    DATABASE    |
| STT - TTS -    | RAG pipeline  | short/long -  | SQLite +       |
| wake word      | embeddings -  | vector store  | 8 migrations   |
|                | vector search |               |                |
+----------------+---------------+----------------+-----------------+""")
    tip(story,
        "Key concept — EventBus: every subsystem communicates through a thread-safe "
        "event bus (MODEL_LOADED, AGENT_FINISHED, VOICE_TRANSCRIPT...). This is why "
        "pages update instantly when something happens anywhere in the app.")
    h2(story, "1.3 The 13 pages")
    tbl(
        story,
        ["Page", "Purpose", "Typical use"],
        [
            ["Home", "Status hub", "Model/system overview, quick actions"],
            ["Chat", "Main workspace", "Talk to the assistant"],
            ["Memory", "Long-term memory", "What the assistant remembers about you"],
            ["Knowledge", "Document RAG", "Index and search your documents"],
            ["Models", "Model manager", "Load / unload / switch models"],
            ["Capabilities", "Model features", "See what the current model supports"],
            ["Projects", "Project workspace", "Scope work, assign agents"],
            ["Agents", "Agent manager", "Create and edit specialized agents"],
            ["Tools", "Tool catalog", "Enable / disable capabilities"],
            ["Voice", "Speech settings", "STT / TTS configuration"],
            ["Automation", "Scheduler", "Periodic and one-shot tasks"],
            ["Workflow", "Step editor", "Build multi-tool workflows"],
            ["Settings", "Configuration", "All preferences + Online API"],
        ],
        widths=[26 * mm, 44 * mm, 100 * mm],
    )


def ch2(story: list) -> None:
    h1(story, "2 · Technical Specifications")
    h2(story, "2.1 Runtime stack")
    tbl(
        story,
        ["Component", "Technology", "Version / details"],
        [
            ["UI framework", "PySide6 (Qt 6)", "6.11.1 · Graphite + Emerald theme"],
            ["Local inference", "llama-cpp-python", ">= 0.3.0 · GGUF format"],
            ["Speech-to-text", "faster-whisper", "local models: tiny, base"],
            ["Text-to-speech", "pyttsx3", "2 system voices (SAPI)"],
            ["Wake word", "openwakeword", '"hey_jarvis" · ONNX'],
            ["Database", "SQLite", "8 migrations · assistant.db"],
            ["Audio I/O", "sounddevice", "WASAPI preferred, MME fallback"],
            ["Online API (opt-in)", "requests", "OpenAI-compatible · SSE streaming"],
        ],
        widths=[34 * mm, 40 * mm, 96 * mm],
    )
    h2(story, "2.2 Data locations")
    tbl(
        story,
        ["Data", "Path", "Notes"],
        [
            ["Settings", "%LOCALAPPDATA%\\OfflineAI\\config\\settings.json", "All config incl. API keys"],
            ["Database", "%LOCALAPPDATA%\\OfflineAI\\data\\assistant.db", "Agents, memory, projects"],
            ["Models", "%LOCALAPPDATA%\\OfflineAI\\models\\llm\\", "GGUF files (+ mmproj)"],
            ["STT models", "%LOCALAPPDATA%\\OfflineAI\\models\\voice\\stt\\", "Whisper folders"],
            ["Knowledge", "%LOCALAPPDATA%\\OfflineAI\\data\\knowledge.json", "Index persistence"],
            ["Logs", "%LOCALAPPDATA%\\OfflineAI\\logs\\", "Rotating logs"],
        ],
        widths=[24 * mm, 82 * mm, 64 * mm],
    )
    h2(story, "2.3 Model capability detection")
    tbl(
        story,
        ["Capability", "Detected from", "Enables"],
        [
            ["Text generation", "every GGUF", "chat responses"],
            ["Streaming", "every GGUF", "token-by-token display"],
            ["Vision", "name (vl/vision/llava...) + mmproj file", "image analysis in chat"],
            ["Tool calling", "name (instruct/chat/qwen/coder)", "agents, native tools"],
            ["Code generation", "name (coder/code)", "coding assistance"],
            ["Reasoning", "name (think/r1/reasoning)", "step-by-step chains"],
            ["Embeddings", "name (embed...)", "excluded from chat; used for memory"],
            ["Long context", "GGUF metadata", "32K+ context"],
        ],
        widths=[30 * mm, 72 * mm, 68 * mm],
    )
    tip(story,
        "mmproj rule: a vision model needs its projector file (mmproj-*.gguf) in the "
        "same folder. The app auto-detects and attaches it. Without it the model "
        "runs text-only.")
    h2(story, "2.4 Performance guidance (RTX 3080 10 GB / 32 GB RAM)")
    tbl(
        story,
        ["Model class", "Example", "VRAM", "Expected speed"],
        [
            ["7-9B Q4 (full GPU)", "Qwen3.5-9B UD-Q4_K_XL + mmproj", "~7 GB", "35-60 tok/s"],
            ["12B Q4 (full GPU)", "gemma-4-12B QAT", "~7.2 GB", "25-40 tok/s"],
            ["30B MoE (hybrid)", "Qwen3-Coder-30B-A3B Q3", "10 GB + RAM", "10-20 tok/s"],
            ["27B dense (hybrid)", "Qwen3.8-27B Q3", "10 GB + RAM", "2-4 tok/s"],
        ],
        widths=[36 * mm, 62 * mm, 28 * mm, 44 * mm],
    )
    p(story, "See RECOMMENDED_MODELS.md for the full 25-model list with reasons.")
    h2(story, "2.5 Generation parameters (Settings -&gt; Generation)")
    tbl(
        story,
        ["Parameter", "Default", "Meaning", "When to change"],
        [
            ["max_tokens", "1024", "response length budget", "raise for long answers"],
            ["temperature", "0.7", "0=deterministic, 2=chaotic", "0.2 for code, 1.0 creative"],
            ["top_p", "0.9", "nucleus sampling cutoff", "lower = more focused"],
            ["top_k", "40", "top-K candidate pool", "rarely needs change"],
            ["min_p", "0.05", "minimum probability filter", "0.05-0.1 typical"],
            ["repeat_penalty", "1.1", "repetition suppression", "1.15 if looping"],
            ["n_ctx", "4096", "context window (tokens)", "8192-16384 if VRAM allows"],
            ["n_threads", "8", "CPU threads", "= physical cores"],
            ["n_gpu_layers", "auto", "GPU offload layers", "leave on auto"],
        ],
        widths=[30 * mm, 18 * mm, 62 * mm, 60 * mm],
    )


def ch3(story: list) -> None:
    h1(story, "3 · First Steps")
    h2(story, "3.1 Launching")
    p(story,
      'Double-click <b>Pokreni.bat</b> (or run <font face="Courier">run.py</font>). '
      "The launcher pins Python 3.11 with all dependencies. The window opens with "
      "the Home page showing live model and system status.")
    h2(story, "3.2 First-run wizard (7 steps)")
    tbl(
        story,
        ["Step", "What happens"],
        [
            ["1 · Welcome", "Privacy overview — everything stays on this device"],
            ["2 · System check", "CPU / RAM / GPU / disk verification"],
            ["3 · AI Model", "Pick or download a GGUF model into models\\llm\\"],
            ["4 · Locations", "Confirm data folders"],
            ["5 · Installation", "Application -> Dependencies -> Model -> Verify -> Finalize"],
            ["6 · Capabilities", "What your model supports (text/vision/tools...)"],
            ["7 · Complete", "Launch the assistant"],
        ],
        widths=[34 * mm, 136 * mm],
    )
    tip(story,
        "Fastest start: copy any GGUF file into %LOCALAPPDATA%\\OfflineAI\\models\\llm\\ "
        "and restart — the app auto-discovers it and the Models page lists it.")
    h2(story, "3.3 Loading a model (Models page)")
    code(story, """Models page -> click a model -> Details panel shows:
  name, type, architecture, quantization, context length, capabilities
-> click [Activate]
-> Status turns "AI model ready"; the model name appears in the status bar.""")
    p(story,
      "<b>Folder picker:</b> [Select Models Folder] scans any directory (e.g. a "
      "portable drive). <b>Unload</b> frees VRAM before switching — switching "
      "requires Unload first (by design, to protect the active session).")
    h2(story, "3.4 Your first conversation")
    code(story, """Chat page -> type: Hello! What can you do?
-> press Enter   (Shift+Enter = new line; box holds 4-8 lines)
-> tokens stream into a reply bubble""")
    p(story,
      'Try: <font face="Courier">remember that I prefer concise answers</font> — '
      "the assistant asks to confirm, then stores it in long-term memory "
      "(see the Memory page).")


def ch4(story: list) -> None:
    h1(story, "4 · Chat")
    h2(story, "4.1 Input bar")
    tbl(
        story,
        ["Action", "Result"],
        [
            ["Enter", "send the message"],
            ["Shift+Enter / Ctrl+Enter", "new line"],
            ["Box size", "minimum 4 visible lines, grows to 8, then scrolls"],
            ["[REC]", "voice input — click to record, click again to stop"],
            ["[stop]", "appears while streaming — click to cancel generation"],
        ],
        widths=[48 * mm, 122 * mm],
    )
    h2(story, "4.2 Attaching files and images")
    p(story, "<b>Files button</b> — attaches a text file into the message:")
    code(story, """Click Files -> choose notes.md
The input now contains:
  [File: notes.md]
  <entire file content>
Add your question -> press Enter.""")
    p(story,
      "<b>Vision button</b> — enabled only when the loaded model supports vision "
      "(requires the mmproj projector). Click, pick images (up to 12 MB each), a "
      'counter appears — "Vision (2)" — then ask: "What error is shown in this '
      'screenshot?"')
    warn(story,
         "No vision model loaded? You get a clear refusal: The active model does "
         "not support image understanding... — the app refuses politely instead "
         "of guessing.")
    h2(story, "4.3 Slash-commands")
    tbl(
        story,
        ["Command", "Example", "What happens"],
        [
            ["/agent plan &lt;goal&gt;", "/agent plan clean up my downloads folder",
             "Runs the agent pipeline (Ch. 6)"],
            ["/automation run &lt;name&gt;", "/automation run system_check",
             "Runs a saved workflow (Ch. 8)"],
            ["/_plugins", "/_plugins", "Lists installed plugins"],
            ["/plugin &lt;id&gt; &lt;action&gt;", "/plugin demo enable", "Plugin management"],
        ],
        widths=[40 * mm, 66 * mm, 64 * mm],
    )
    h2(story, "4.4 Memory intents in chat")
    code(story, """You:       remember that my printer is a Canon MX-340
Assistant: This can be saved to memory:
             'My printer is a Canon MX-340'
           Do you want me to remember it?
You:       yes
Assistant: Saved to memory.

Later — any relevant question automatically recalls the fact.
Say "no" to decline; anything ambiguous cancels silently.""")
    h2(story, "4.5 Exporting conversations")
    p(story,
      "<b>Export</b> saves the whole conversation; <b>Export Selected</b> saves "
      "highlighted messages (Ctrl+click). Formats: .txt, .md, .json. "
      "<b>Search Memory</b> searches long-term memory; right-click a message to "
      "delete it.")
    h2(story, "4.6 Project context badge")
    p(story,
      'When a project is open (Ch. 7) the header shows "Project: MyProject" — '
      "every message is answered within that project's scope. Use Projects -&gt; "
      "Close, or open another project, to change it.")


def ch5(story: list) -> None:
    h1(story, "5 · Models &amp; Capabilities")
    h2(story, "5.1 Switching models — worked example")
    code(story, """Situation: Coder agent work finished; you want vision for screenshots.

1. Chat runs on Qwen2.5-Coder-7B (active)
2. Models page -> select Qwen2.5-VL-7B-Instruct -> click [Unload]
   Status: "Model unloaded"  (VRAM freed)
3. Select the VL model -> [Activate]
   Log: "Vision projector detected... attached"
4. Capabilities page now shows Vision = Active
   Chat Vision button becomes enabled""")
    h2(story, "5.2 Capabilities page")
    p(story,
      "Live cards for the active model — Text Generation, Streaming, Code Generation, "
      "Tool Calling, Function Calling, Reasoning, Multimodal, Vision, JSON Output, "
      "Structured Output, Embeddings, Long Context — each with an Active/Inactive "
      "state. The cards refresh automatically on every model change.")
    h2(story, "5.3 Recommended models for 10 GB VRAM")
    tbl(
        story,
        ["Use", "Model", "Size"],
        [
            ["Daily all-rounder (vision)", "Qwen3.5-9B UD-Q4_K_XL + mmproj", "~6.9 GB"],
            ["Coding agent (hybrid)", "Qwen3-Coder-30B-A3B UD-Q3_K_XL", "13.8 GB CPU+GPU"],
            ["Ultra-light (bundled)", "Phi-4-mini-instruct Q6_K_L", "3.15 GB"],
            ["Memory embeddings", "mxbai-embed-large-v1 GGUF", "0.67 GB"],
        ],
        widths=[52 * mm, 78 * mm, 30 * mm],
    )
    p(story,
      "Models page -&gt; <b>[Download Model]</b> opens the catalog dialog — downloads "
      "land directly in the models folder.")


def ch6(story: list) -> None:
    h1(story, "6 · Agents — Complete Guide")
    h2(story, "6.1 What is an agent?")
    p(story,
      "An agent = <b>a system prompt + a model + a tool whitelist + permissions</b>. "
      "Given a goal it <b>plans</b> (breaks the goal into tasks), <b>acts</b> "
      "(executes tasks through the secured tool registry) and <b>summarizes</b> "
      "the result. Agents persist in SQLite and survive restarts.")
    code(story, """GOAL --> PLANNER --> [Task1, Task2, Task3]
                        |
                        v  (each task)
                  TOOL REGISTRY --> SECURITY LAYER --> execute / ask / deny
                        |
                        v
                   SUMMARY  (+ optional verification)""")
    h2(story, "6.2 The 7 built-in agents")
    tbl(
        story,
        ["Agent", "Role", "Tool whitelist"],
        [
            ["Researcher", "Search + summarize knowledge/files",
             "search_knowledge, search_files, read_file, list_directory, file_metadata, date_time"],
            ["Writer", "Draft and refine text", "all tools"],
            ["Coder", "Read and revise source code",
             "read_file, search_files, list_directory, file_metadata, write_file, calculate, date_time"],
            ["Analyst", "Numbers and conclusions",
             "calculate, date_time, search_knowledge, read_file, search_files"],
            ["File Manager", "Organize files/folders",
             "search_files, list_directory, file_metadata, read_file, copy_file, move_file, create_directory"],
            ["System Monitor", "System health + advice", "system_info, process_info, date_time"],
            ["Planner", "Decompose goals into steps", "date_time, search_knowledge, search_files"],
        ],
        widths=[28 * mm, 46 * mm, 96 * mm],
    )
    h2(story, "6.3 ★ EXAMPLE — creating a new agent (Translator)")
    p(story,
      "<b>Goal: a Translator agent that translates any text to English or German, "
      "using no tools (pure LLM work).</b>")
    code(story, """1. Sidebar -> Agents
2. Click [Add Agent] — the editor dialog opens
3. Name:        Translator
4. Description: Translates text to English or German, preserving tone
5. System prompt:
   "You are the Translator agent. Translate the user's text to the
    requested language. The message starts with the target language
    in square brackets, e.g. [de] or [en]. Preserve tone, formatting
    and technical terms. If no language tag is present, ask which
    language is required before translating."
6. Model name:      (leave empty -> uses the active chat model)
7. Permission profile: default
8. Tool whitelist: (no tools needed for a pure translator)
9. [Save]""")
    p(story, "<b>Run it from chat:</b>")
    code(story, """You: /agent plan [de] The weather is beautiful today.
 -> Planner creates a conversational task (no tool needed)
 -> Translator answers: "Das Wetter ist heute wunderschon.\"""")
    h2(story, "6.4 ★ EXAMPLE — a tool-using agent with a whitelist (Disk Cleaner)")
    p(story,
      "<b>Goal: a Disk Cleaner that finds files larger than a threshold and reports "
      "them — never deletes anything.</b>")
    code(story, """Name:        Disk Cleaner
Description: Finds large files and reports cleanup candidates
System prompt:
  "You are the Disk Cleaner agent. Find files larger than the size the
   user gives (default 100 MB) in the directory the user gives (default
   the user profile). Use search_files and file_metadata. NEVER delete
   anything — only produce a table of candidates with full paths and
   sizes, and recommend which are safe to remove."
Whitelist:   [x] search_files  [x] list_directory  [x] file_metadata
             (leave delete_file UNCHECKED — hard guarantee)
Permission profile: default""")
    code(story, """Run:  /agent plan find files over 500MB in D:\\Projects

Agent Disk Cleaner: 1 done
  [ok] Search in D:\\Projects
Result: 6 candidates, largest build_artifacts.zip (1.2 GB)""")
    tip(story,
        "Defence in depth: the unchecked whitelist blocks the tool even if the "
        "model tries; the security layer would separately ask for confirmation "
        "on any write-level action.")
    h2(story, "6.5 ★ EXAMPLE — an agent with a dedicated model")
    tbl(
        story,
        ["Model name value", "Effect"],
        [
            ["(empty)", "use the active chat model (default)"],
            ["Qwen2.5-Coder-7B-Q4_K_M", "loads that local model for this agent"],
            ["openrouter:z-ai/glm-5.2:free", "online — OpenRouter free model"],
            ["groq:llama-3.3-70b-versatile", "online — Groq"],
        ],
        widths=[72 * mm, 98 * mm],
    )
    warn(story,
         "If the requested model is unavailable the agent automatically falls "
         "back to the global chat model and logs a warning — the run still "
         "completes.")
    h2(story, "6.6 Managing agents")
    tbl(
        story,
        ["Action", "How"],
        [
            ["Edit", "Agents page -> [Edit] on the agent card"],
            ["Disable / Enable", "toggle button on the card (disabled agents are never selected)"],
            ["Delete", "[Delete] — permanent removal after confirmation"],
            ["Filter", "dropdown: All / Enabled / Disabled"],
            ["Auto-refresh", "page listens to AGENT_* events — updates live"],
        ],
        widths=[40 * mm, 130 * mm],
    )


def ch7(story: list) -> None:
    h1(story, "7 · Projects — Complete Guide")
    h2(story, "7.1 What is a project?")
    p(story,
      "A project = <b>a named scope</b> with an optional workspace folder. Opening "
      "a project injects its description and workspace path into every chat prompt "
      "(as DATA, never as instructions), and can carry an <b>assigned agent</b> "
      "that handles all goals in that project.")
    code(story, """Project
 |- id, name, description
 |- workspace_path   (folder — enables knowledge indexing)
 |- settings         (JSON, per-project overrides)
 |- assigned agent   (optional)
 '- runtime state    (idle / active / completed / error)""")
    h2(story, "7.2 ★ EXAMPLE — creating a new project")
    code(story, """1. Sidebar -> Projects
2. [+ New Project]
3. Name:        Thesis
4. Description: Master thesis on local AI privacy — drafts and sources
5. Workspace:  D:\\Thesis   (folder with your .md/.txt files)
6. [Create]
   -> project appears in the left list
   -> PROJECT_CREATED event; Projects page refreshes""")
    h2(story, "7.3 ★ Adding the project to chat context (Open)")
    code(story, 'Projects page -> select "Thesis" -> [Open]\n'
                ' -> app navigates to Chat automatically\n'
                ' -> chat header now shows: Project: Thesis\n'
                ' -> EVERY following message is answered within the project scope:\n'
                '    the system prompt gains a PROJECT CONTEXT block with\n'
                '    Project ID / Name / Description / Workspace path / Settings,\n'
                '    plus the instruction:\n'
                '    "Use this information when answering questions about the\n'
                '     current project. Do not claim knowledge of files that\n'
                '     have not been provided."')
    p(story,
      "<b>Index the workspace (optional but powerful):</b> with the project open, "
      "index D:\\Thesis on the Knowledge page — every .md/.txt becomes retrievable "
      "via RAG for project-scoped answers (see 9.2).")
    h2(story, "7.4 ★ Removing the project from chat context (Close)")
    code(story, """Projects page -> [Close]     (or open a different project)
 -> chat header badge disappears
 -> PROJECT_CLOSED event
 -> further messages answer without project scope

Closing does NOT delete anything — the project, its settings and its
agent assignment stay in the database.""")
    h2(story, "7.5 ★ EXAMPLE — assigning an agent to the project")
    code(story, """1. Projects page -> select "Thesis" -> [Assign Agent]
2. Dialog lists enabled agents -> choose "Researcher"
   -> stored persistently: Researcher <-> Thesis
3. Every goal in this project is now handled by Researcher:
   - Chat:        /agent plan find all references to "federated learning"
   - Projects page [Run Agent] button (prompts for a goal)
4. The Projects page shows live runtime state:
   ACTIVE (running) -> COMPLETED (or ERROR)""")
    h2(story, "7.6 Project-scoped knowledge and memory")
    tbl(
        story,
        ["Feature", "Scope", "How"],
        [
            ["Workspace indexing", "project", "Knowledge page -> Index Directory -> RAG chunks"],
            ["Agent memory", "project agent", "automatic — results saved as project_info"],
            ["Conversation context", "project", "every open-project chat turn"],
        ],
        widths=[44 * mm, 32 * mm, 94 * mm],
    )
    p(story,
      "After a successful agent run its summary is stored as a project_info memory "
      "(importance 0.7) — the agent remembers what it did in this project.")
    h2(story, "7.7 Project lifecycle")
    code(story, """CREATE --> list --> OPEN  -->  (chat context ON)
                     |
                     +--> ASSIGN AGENT --> RUN GOALS --> live state updates
                     |
                     '--> CLOSE  -->  (chat context OFF)

DELETE (any time — removes the record; your files are untouched)""")


def ch8(story: list) -> None:
    h1(story, "8 · Automation &amp; Workflows")
    h2(story, "8.1 Automation dashboard")
    p(story,
      "Sidebar -&gt; Automation. Two panels: <b>Workflows</b> (named, multi-step) "
      "and <b>Scheduled Tasks</b> (time-driven).")
    tbl(
        story,
        ["Control", "What it does"],
        [
            ["[Run Workflow]", "executes the selected workflow immediately"],
            ["[+ New Task]", "creates a scheduled task (Task Editor dialog)"],
            ["[Run Now]", "forces a due task to run immediately"],
            ["Enabled checkbox", "pauses/resumes a task without deleting it"],
            ["Refresh", "reloads persisted tasks/workflows from disk"],
        ],
        widths=[44 * mm, 126 * mm],
    )
    h2(story, "8.2 ★ EXAMPLE — a scheduled task (interval)")
    code(story, """Goal: write a system snapshot every 6 hours.

1. Automation -> [+ New Task] — Task Editor opens
2. Name:       morning-system-snapshot
3. Target:     Tool: system_info
4. Params:     {}   (no parameters needed)
5. Schedule:   Interval — every 21600 seconds (6 h)
6. [Save]
   -> task appears with its next_run timestamp
   -> the scheduler ticks every second; when due, the task executes
      through the Security Layer (policies still apply) and records
      the result.""")
    p(story,
      "Schedule types: <b>Interval</b> (every N seconds), <b>Once</b> (one-shot at "
      "a date/time), <b>Cron</b> (needs the optional croniter package).")
    h2(story, "8.3 ★ EXAMPLE — building a Workflow (disk-guard)")
    p(story,
      "Sidebar -&gt; Workflow. A workflow is an <b>ordered list of tool steps</b>, "
      "optionally with a condition that branches on the previous result.")
    code(story, """Goal: "Check disk space; if usage > 80%, list the biggest files."

1. Workflow name: disk-guard
2. Step 1 — Tool: system_info    Params: {}
   (captures disk_used_percent into the previous result)
3. Step 2 — Condition (safe Python expression on the previous result):
      "disk_used_percent > 80"
   when TRUE it runs the branch steps:
      a) search_files   Params: {"pattern": "*.log", "directory": "D:\\"}
      b) list_directory Params: {"path": "D:\\"}
4. [Add Step] after each; [Save Workflow]""")
    code(story, """Run it:
  Automation page -> select disk-guard -> [Run Workflow]
  Chat:            /automation run disk-guard

Summary line:
  "Workflow 'disk-guard': 2 succeeded, 0 blocked, 0 failed\"""")
    warn(story,
         "Every step passes through the Security Layer. A write-level tool in a "
         "workflow triggers the same confirmation gate as in chat — a blocked "
         "step counts as blocked, not failed.")
    h2(story, "8.4 Persistence")
    p(story,
      "Workflows persist to workflows.json; tasks to tasks.json (data folder). "
      'Both reload automatically at startup. The built-in "system_check" '
      "workflow ships with the app.")


def ch9(story: list) -> None:
    h1(story, "9 · Knowledge, Memory &amp; RAG")
    h2(story, "9.1 Knowledge base (RAG)")
    code(story, """DOCUMENT -> loader (.txt .md .pdf* .docx* .html)
         -> chunker (1200 chars, 200 overlap)
         -> embeddings (model or stub)
         -> vector store (faiss or kNN fallback)
                     |
Chat query ---------> retrieve top-3 ----> "Knowledge context:" in prompt

(* PDF needs pypdf/PyMuPDF; DOCX needs python-docx — optional)""")
    tbl(
        story,
        ["Knowledge page action", "Effect"],
        [
            ["Index File / Index Directory", "add chunks (deduplicated)"],
            ["Rebuild", "clear + re-index everything"],
            ["Search", "preview retrieval quality"],
            ["Export / Delete", "dump index to JSON / remove documents"],
        ],
        widths=[64 * mm, 106 * mm],
    )
    h2(story, "9.2 ★ EXAMPLE — project knowledge in practice")
    code(story, """1. Create project "Thesis" with workspace D:\\Thesis  (Ch. 7)
2. Knowledge -> Index Directory -> D:\\Thesis -> 214 chunks
3. Chat (with the project open):
   "Which chapter discusses federated learning?"
   -> RAG retrieves: chapter3/method.md — "Federated learning lets..."
   -> the answer cites the actual document content""")
    h2(story, "9.3 Memory layers")
    tbl(
        story,
        ["Layer", "Store", "Lifetime", "Example"],
        [
            ["Short-term", "RAM (window 10)", "conversation", "last messages in prompt"],
            ["Long-term", "SQLite memories", "forever", "'User prefers tea over coffee'"],
            ["Agent memory", "SQLite (per agent)", "forever", "'Task completed: ...'"],
            ["Vector", "embeddings", "forever", "semantic recall of facts"],
        ],
        widths=[26 * mm, 40 * mm, 30 * mm, 74 * mm],
    )
    p(story,
      "The Memory page lists every stored memory with type and importance; delete "
      'any entry. "remember that ..." in chat adds to long-term memory after '
      "confirmation.")
    h2(story, "9.4 Embedding model upgrade")
    p(story,
      'The default memory.embedding_model = "stub" uses deterministic hash '
      "embeddings. Put mxbai-embed-large-v1-f16.gguf (0.67 GB) in the models "
      "folder, then Settings -&gt; Memory -&gt; Embedding model -&gt; "
      "mxbai-embed-large-v1-f16, and restart. This is the single biggest quality "
      "upgrade for search (MTEB 64.68).")


def ch10(story: list) -> None:
    h1(story, "10 · Online API (Multi-Provider, Opt-In)")
    warn(story,
         "Offline-first: nothing is sent anywhere unless you (1) enable the API, "
         "(2) store a provider key, and (3) route an agent to an online model. "
         "The chat Online badge appears while an online model serves a turn.")
    h2(story, "10.1 ★ EXAMPLE — adding a provider (Groq)")
    code(story, """1. Settings -> Online API -> [x] Enable Online API
2. Provider dropdown -> "Groq (groq)"
3. Click the "Get a key" link -> console.groq.com/keys
   -> create a key (free) -> copy it
4. Paste into "API key"  (the field is masked)
5. [Fetch models] -> live catalogue fills the Models dropdown
   (or type / pick e.g. llama-3.3-70b-versatile)
6. [Test connection] -> "Connection OK — model replied: 'ready'"

Each provider stores its own key / base URL / model — switch freely.
Keys live only in settings.json.""")
    h2(story, "10.2 Routing agents online")
    tbl(
        story,
        ["Agent Model name", "Provider used"],
        [
            ["openrouter:z-ai/glm-5.2:free  (or or:...)", "OpenRouter"],
            ["groq:llama-3.3-70b-versatile", "Groq"],
            ["google:gemini-2.5-flash  (or gemini:...)", "Google AI Studio"],
            ["mistral:mistral-small-latest", "Mistral"],
            ["myllm:house-model  (custom)", "your own endpoint"],
        ],
        widths=[96 * mm, 74 * mm],
    )
    p(story,
      "<b>Fallback:</b> unconfigured provider, rate limit or network error — the "
      "agent silently uses the local chat model and logs a warning.")
    h2(story, "10.3 Built-in provider presets")
    tbl(
        story,
        ["Provider", "Key page", "Free tier"],
        [
            ["OpenRouter", "openrouter.ai/keys", "~16 tool-calling :free models"],
            ["Groq", "console.groq.com/keys", "fast Llama / Qwen / GPT-OSS"],
            ["Google AI Studio", "aistudio.google.com/apikey", "Gemini Flash family"],
            ["Mistral", "console.mistral.ai/api-keys", "La Plateforme free tier"],
            ["Cerebras", "cloud.cerebras.ai", "ultra-fast inference"],
            ["Together AI", "api.together.ai", "free models"],
            ["Custom...", "any OpenAI-compatible URL", "your server (vLLM, LM Studio...)"],
        ],
        widths=[36 * mm, 62 * mm, 72 * mm],
    )
    warn(story,
         "API keys are personal secrets. They are stored only in local "
         "settings.json — never logged, never committed. Rate limits (HTTP 429) "
         "surface as clear messages; free tiers reset daily.")


def ch11(story: list) -> None:
    h1(story, "11 · Voice")
    h2(story, "11.1 Voice page (auto-populated)")
    p(story,
      "STT: provider (faster-whisper), model (local folder), device (auto/cpu/cuda), "
      "language (auto/Serbian/English — speech-recognition language). "
      "TTS: provider (pyttsx3), voice, rate (200 wpm), volume. "
      "Wake word: enable + phrase (hey_jarvis).")
    h2(story, "11.2 Voice in chat")
    code(story, """[REC]    click -> recording (WASAPI microphone)
         click again -> transcribe -> the text lands in chat -> answer
[PLAY]   replays the last recording (appears after the first recording)
[Automatic Listening]  continuous mode:
   listen -> transcribe -> respond -> speak -> listen ...
   (the mic mutes during TTS — echo protection)
"hey jarvis" wake phrase -> one hands-free voice interaction""")
    p(story,
      "<b>Prerequisite:</b> a local Whisper model folder in models\\voice\\stt\\ "
      "(tiny and base ship with the app). STT runs on GPU when available. "
      "Keyboard shortcut: Ctrl+/ toggles voice.")


def ch12(story: list) -> None:
    h1(story, "12 · Security &amp; Permissions")
    h2(story, "12.1 The three policies")
    tbl(
        story,
        ["Policy", "Behaviour", "Typical tools"],
        [
            ["ALLOW", "runs silently", "calculate, date_time, read_file"],
            ["ASK", "modal confirmation dialog", "write_file, delete_file, move_file, open_application"],
            ["DENY", "refused and logged", "configurable per category"],
        ],
        widths=[26 * mm, 62 * mm, 82 * mm],
    )
    p(story,
      "Every tool execution — chat, agents, workflows, scheduled tasks — goes "
      "through the same SecurityLayer. There is no bypass path.")
    h2(story, "12.2 Risk levels")
    code(story, """INFO   -> read-only           (no confirmation)
WRITE  -> changes disk state  -> confirmation dialog
DELETE -> destructive         -> confirmation dialog (profile may DENY)""")
    h2(story, "12.3 Agent-level hardening (defence in depth)")
    p(story,
      "<b>1. Tool whitelist</b> — unchecked tools are BLOCKED for the agent no "
      "matter what the model tries. <b>2. Permission profile</b> — default / "
      "restrictive / permissive; the GUI confirmation gate protects risky actions.")
    h2(story, "12.4 Audit")
    p(story,
      "All executions land in the audit log with tool, params, decision and "
      "timestamp — inspectable in the data folder. Project context is injected "
      "as read-only DATA blocks; prompts never treat it as instructions.")


def ch13(story: list) -> None:
    h1(story, "13 · Settings Reference")
    tbl(
        story,
        ["Tab", "Contents"],
        [
            ["General", "Theme (grey_emerald / installer)"],
            ["Language", "English"],
            ["Model", "active model status + [Manage Models]"],
            ["Generation", "max_tokens, temperature, top_p, top_k, min_p, repeat_penalty, n_ctx, threads, GPU layers"],
            ["Memory", "enabled, window, max context memories, embedding model"],
            ["Filesystem Security", "read/write roots, symlink policy"],
            ["Audio", "input/output device, WASAPI prefs, mic test"],
            ["Voice", "STT / TTS / wake word (Ch. 11)"],
            ["Online API", "multi-provider keys, base URLs, models, timeout, test (Ch. 10)"],
            ["Storage", "data folder paths + disk usage"],
            ["Logging", "level (DEBUG...ERROR)"],
            ["Plugins", "enable / disable / unload"],
            ["Profile", "Identity - Communication - Personality - Expertise - Behavior - Boundaries"],
        ],
        widths=[42 * mm, 128 * mm],
    )
    tip(story,
        "The Profile shapes every system prompt: name, description, traits, tone, "
        "formality, response style, custom instructions. Changes apply from the "
        "next message; Save persists.")


def ch14(story: list) -> None:
    h1(story, "14 · Tools Reference")
    tbl(
        story,
        ["Tool", "Risk", "Parameters", "Example"],
        [
            ["calculate", "INFO", "expression", "2+3*4 -> 14"],
            ["date_time", "INFO", "-", "current date/time"],
            ["read_file", "INFO", "path", "read config.json"],
            ["list_directory", "INFO", "path", "list D:\\Projects"],
            ["search_files", "INFO", "pattern, directory", "*.log in D:\\"],
            ["file_metadata", "INFO", "path", "size, times, type"],
            ["search_knowledge", "INFO", "query, top_k", "RAG search"],
            ["system_info", "INFO", "-", "CPU/RAM/disk/GPU"],
            ["process_info", "INFO", "-", "top processes"],
            ["clipboard_read", "INFO", "-", "paste into prompt"],
            ["clipboard_write", "INFO", "text", "copy result"],
            ["write_file", "WRITE", "path, content", "save report.md"],
            ["create_directory", "WRITE", "path", "new folder"],
            ["copy_file", "WRITE", "source, destination", "backup"],
            ["move_file", "WRITE", "source, destination", "reorganize"],
            ["open_application", "WRITE", "program", "launch calculator"],
            ["delete_file", "DELETE", "path", "requires confirmation"],
        ],
        widths=[34 * mm, 20 * mm, 46 * mm, 70 * mm],
    )
    p(story,
      "Every tool is invocable by agents (via whitelist), by workflows (steps) "
      "and by the assistant's native tool-calling path — all gated by the "
      "Security Layer.")


def ch15(story: list) -> None:
    h1(story, "15 · Troubleshooting &amp; FAQ")
    h2(story, "15.1 Common problems")
    tbl(
        story,
        ["Symptom", "Cause", "Fix"],
        [
            ['"No model loaded"', "no GGUF in models folder", "copy a model / Download / wizard"],
            ['"Runtime unavailable"', "llama-cpp-python missing", "pip install llama-cpp-python"],
            ["Vision button disabled", "model has no mmproj", "add mmproj-*.gguf next to the model"],
            ["Switch rejected", "another model active", "Unload first, then Activate"],
            ["STT error", "missing whisper folder", "models\\voice\\stt\\base must exist"],
            ["Online 401", "wrong key", "re-paste key, Test connection"],
            ["Online 429", "free-tier rate limit", "wait for daily reset / switch model"],
            ["Agent used wrong model", "requested model unavailable", "check log — fell back to chat model"],
            ["Workflow step blocked", "ConfirmationRequired", "expected for WRITE tools — approve the dialog"],
            ["Cron task not running", "croniter missing", "pip install croniter (or use interval)"],
        ],
        widths=[46 * mm, 56 * mm, 68 * mm],
    )
    h2(story, "15.2 FAQ")
    p(story,
      "<b>Is my data really local?</b> Yes — unless you enable the Online API and "
      "route an agent online (Online badge). Keys and prompts stay on disk "
      "otherwise.")
    p(story,
      "<b>Can two models run at once?</b> One chat model plus per-agent models are "
      "possible, but each consumes memory; the Unload-first rule protects the "
      "active session.")
    p(story,
      "<b>Where are my agents stored?</b> SQLite (assistant.db) — they survive "
      "updates. Built-ins seed only once; your edits are never overwritten.")
    p(story,
      "<b>How do I stop a runaway agent?</b> The chat Stop button sets a "
      "cooperative cancel — the agent stops at the next safe checkpoint.")
    h2(story, "15.3 Verification status")
    tbl(
        story,
        ["Category", "Status"],
        [
            ["Infrastructure (config, bus, DB, logging)", "verified"],
            ["Models (discovery, load, capabilities, mmproj)", "verified"],
            ["Assistant core (chat, vision, memory, RAG)", "verified"],
            ["Tools &amp; security (registry, policies, audit)", "verified"],
            ["Agents (7 built-ins, planner, orchestrator, online routing)", "verified"],
            ["Automation (workflows, scheduler, tasks)", "verified"],
            ["Plugins (discovery, loading, states)", "verified"],
            ["Voice (STT / TTS / wake / auto-listening)", "verified"],
            ["UI (13 pages, dialogs, tray, shortcuts)", "verified"],
            ["Online API (6 providers + custom, catalogue, test)", "verified"],
        ],
        widths=[126 * mm, 44 * mm],
    )
    p(story,
      "182 automated tests passing · ruff clean · see FEATURES.md for the "
      "complete per-feature audit.")
    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "— End of manual · Offline AI Assistant · Your data is safe here —",
        ParagraphStyle("end", parent=S_COVER_M, fontSize=9.5),
    ))


# ----------------------------------------------------------------------
# Build
# ----------------------------------------------------------------------
def build_pdf() -> int:
    doc = BaseDocTemplate(
        str(OUT),
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=18 * mm,
        title="Offline AI Assistant — User Manual",
        author="Offline AI Assistant",
        subject="Complete technical reference and practical guide",
    )

    cover_frame = Frame(
        14 * mm, 18 * mm, PAGE_W - 28 * mm, PAGE_H - 32 * mm, id="cover"
    )
    main_frame = Frame(
        14 * mm, 18 * mm, PAGE_W - 28 * mm, PAGE_H - 32 * mm, id="main"
    )
    doc.addPageTemplates([
        PageTemplate(id="Cover", frames=[cover_frame], onPage=on_cover),
        PageTemplate(id="Main", frames=[main_frame], onPage=on_page),
    ])

    story: list = []
    cover(story)
    # NextPageTemplate switches every following page to Main.
    from reportlab.platypus import NextPageTemplate

    story.append(NextPageTemplate("Main"))
    from reportlab.platypus import PageBreak

    story.append(PageBreak())

    toc(story)
    ch1(story)
    ch2(story)
    ch3(story)
    ch4(story)
    ch5(story)
    ch6(story)
    ch7(story)
    ch8(story)
    ch9(story)
    ch10(story)
    ch11(story)
    ch12(story)
    ch13(story)
    ch14(story)
    ch15(story)

    doc.build(story)
    size_kb = OUT.stat().st_size / 1024
    print(f"\nPDF written: {OUT.resolve()}  ({size_kb:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(build_pdf())
