# Dokumentacija — Offline AI Assistant Redizajn

Ovaj folder je **jedini izvor istine** za plan i napredak redizajna. Ažurira se posle svakog uspešno završenog koraka.

## Sadržaj

| Dokument | Svrha | Kada se ažurira |
|---|---|---|
| [`project_plan.md`](project_plan.md) | **PLAN** — mapa svih koraka (9 faza, 47 koraka), zavisnosti, verifikacioni kriterijumi | Retko (samo kad se plan strukturu promeni) |
| [`current_status.md`](current_status.md) | **STATUS** — praćenje napretka po koracima, dnevnik promena, otvoreni problemi | **Posle svakog uspešno rešenog koraka** |
| [`design_system.md`](design_system.md) | Kompletna specifikacija ciljnog izgleda (palete, komponente, layout) iz `Izgled Aplikaccije/` | Kad se dizajn odluči izmeniti |
| [`models_report.md`](models_report.md) | Analiza kandidata iz E:\models, odluka o modelima, putanje, inference parametri | Kad se promeni izbor modela |
| [`environment.md`](environment.md) | Hardver, Python okruženja (3.11 verified), standardne komande, runtime putanje | Kad se promeni okruženje |
| [`qa_checklist.md`](qa_checklist.md) | Definicija "bez regresije" — smoke suite, funkcionalna matrica F1–F20, vizuelne provere | Stabilna |

## Kako raditi (workflow)

1. Pročitaj `project_plan.md` — nađi prvi ne-završeni korak (po redosledu faza).
2. Izvrši korak.
3. Verifikuj prema koloni "Verifikacija" u planu + relevantne stavke iz `qa_checklist.md`.
4. Ažuriraj `current_status.md`: promeni status koraka (⬜→✅), procenat faze, dodaj red u "Dnevnik promena".
5. Commit.

## Kratki sažetak stanja (2026-09-04)

- Analiza završena; launcher sadrži potvrđen `NameError` bug (popravka u koraku 1.1)
- Modeli izabrani i **kopirani u projekat**: Qwen2.5-Coder-7B Q4_K_M (primarni) + Phi-4-mini Q6_K_L (sekundarni)
- Razvoj na **Python 3.11.9** (llama-cpp-python nedostupan na 3.14)
- Sledeći korak: **0.1 Git init** → **0.3 Baseline test suite** → FAZA 1
