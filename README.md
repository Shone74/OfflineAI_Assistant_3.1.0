# Offline AI Assistant — Final Application

## What this is
`Finalna Aplikacija` is a standalone, independently runnable build of the Offline AI Assistant. It is intended for end-user testing outside the developer workspace.

## Requirements
- Python >= 3.13
- Windows 10/11
- A local AI model in `.gguf` format for real chat
- Ollama/LM Studio models are discovered automatically if present

## First launch
1. Install dependencies: `pip install -r requirements.txt`
2. Launch: `python run.py`
3. On first run the app creates local folders under `%LOCALAPPDATA%\OfflineAI\` for config, data, logs, and models.
4. If no model is available, the first-run wizard helps you choose one.

## Notes
- The application is offline/local-only.
- Voice, knowledge indexing, and some model features are optional.
- Do not delete the `data`, `config`, `logs`, or `models` folders while the app is running.
