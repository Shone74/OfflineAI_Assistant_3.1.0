# START HERE — Offline AI Assistant Final Application

## Launch
Double-click `run.py` or run:
```
python run.py
```

## First launch
On first launch the app creates local folders under `%LOCALAPPDATA%\OfflineAI\`:
- `config\settings.json`
- `data\assistant.db`
- `logs\`
- `models\llm\`

## Models
Real chat requires a local `.gguf` model. Place it in:
```
%LOCALAPPDATA%\OfflineAI\models\llm\
```

The app discovers GGUF models, Ollama storage, and LM Studio directories automatically.

## Requirements
- Python >= 3.13
- Windows 10/11
- See `requirements.txt`

## Troubleshooting
- If the app fails to start, check `%LOCALAPPDATA%\OfflineAI\logs\` for error details.
- If no model is available, the app will start in a limited mode. Use the Models page to add or select a model.
