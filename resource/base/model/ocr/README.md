# OCR model

The files in this directory are the PaddleOCR PP-OCRv4 test assets bundled with
the sibling MaaFramework checkout:

- `det.onnx`: Chinese PP-OCRv4 detection model.
- `rec.onnx` and `keys.txt`: English PP-OCRv4 recognition model (includes digits).

They are loaded by MaaFramework as the default `model/ocr` model and are used by
the automatic-treatment duration recognizer.
