"""tft/cv - LLM-free computer vision for the TFT HUD (docs/TFT_PROGRAM.md section 3).

Slice TFT-04 ships three modules:

- ``profile``    region map authored once at 2560x1440 native
                 (``config/tft_regions/2560x1440.json``) and scaled to any frame of
                 the same aspect ratio (1280x720 relay frame, 1920x1080 client).
- ``layout``     cheap colour probes that decide which HUD panels are on screen;
                 a hidden panel makes its fields ``absent``, never a guess.
- ``ocr_fields`` deterministic OCR reads (Tesseract behind an engine seam) of
                 stage, timer, gold, level, XP, streak, odds, shop offers,
                 scoreboard HP and the trait panel, each as a value envelope
                 (value, conf, src) per section 1.1.
"""

EXTRACTOR_VERSION = "tft-cv-ocr-1"
