# YOLO model weights

This folder is intended to hold YOLO `.pt` weights (e.g. `yolov8n.pt`, `yolov8s.pt`).
The first time Ultralytics loads a model by name, it will auto-download it here.

The weight files themselves are excluded from git (see `.gitignore`).

## Optional face attributes

The live face pipeline can also expose apparent age/gender labels when these
OpenCV DNN files are present locally:

- `age_deploy.prototxt`
- `age_net.caffemodel`
- `gender_deploy.prototxt`
- `gender_net.caffemodel`

Without those files, Face ID still works and YOLO still detects people, but
the extra `hombre` / `mujer` / `nino` labels stay disabled.
