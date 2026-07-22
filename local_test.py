"""Run YOLO buoy model on local webcam — debug view with bounding boxes."""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="model/best.pt")
    parser.add_argument("--camera", default="0")
    parser.add_argument("--conf", type=float, default=0.25)
    args = parser.parse_args()

    model_path = Path(args.model)
    if not model_path.is_file():
        raise FileNotFoundError(f"Model tidak ditemukan: {model_path}")

    from ultralytics import YOLO

    model = YOLO(str(model_path))
    src = int(args.camera) if str(args.camera).isdigit() else args.camera
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        raise RuntimeError(f"Kamera {args.camera} tidak bisa dibuka")

    print(f"Model: {model_path}  classes={list(model.names.values())}")
    print("Tekan Q atau ESC untuk berhenti.")

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        results = model.predict(frame, conf=args.conf, verbose=False)[0]

        for box in results.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            conf = float(box.conf[0])
            cls = int(box.cls[0])
            label = results.names[cls]

            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 255), 2)
            text = f"{label} {conf:.0%}"
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
            cv2.rectangle(frame, (x1, y1 - th - 6), (x1 + tw + 6, y1), (0, 255, 255), -1)
            cv2.putText(frame, text, (x1 + 3, y1 - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2)

        detected = len(results.boxes)
        cv2.putText(
            frame, f"buoy: {detected}", (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2,
        )

        cv2.imshow("Buoy Detection - tekan Q", frame)
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
