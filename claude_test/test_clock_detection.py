# Purpose: pre-flight check for T2 -- does yolov8n (COCO "clock",
# class 74) detect the LED desk clock in the board-camera view? If it
# does not, every T2 trial fails at s1 regardless of agent skill, so
# the task is not viable with this clock/model.
import sys

from ultralytics import YOLO

frame = sys.argv[1] if len(sys.argv) > 1 else "claude_test/rgb_burst/boardcam_clock.jpg"
model = YOLO("yolov8n.pt")

# Low conf to see everything the model considers.
results = model(frame, conf=0.05, verbose=False)
r = results[0]
names = r.names
print(f"frame: {frame}")
print(f"detections (conf >= 0.05): {len(r.boxes)}")
clock_hits = []
for box in r.boxes:
    cls = int(box.cls[0])
    conf = float(box.conf[0])
    label = names[cls]
    print(f"  {label:<15} conf={conf:.3f}")
    if label == "clock":
        clock_hits.append(conf)

print()
if clock_hits:
    print(f"CLOCK DETECTED: best conf {max(clock_hits):.3f}")
else:
    print("NO CLOCK CLASS -- yolov8n does not recognise this display as a clock")
