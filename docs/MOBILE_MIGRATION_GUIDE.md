# Mobile Migration Guide

This guide explains how to transition your Python prototype logic into a production-ready mobile application (iOS/Android).

## 1. The Workflow: Prototype to Production

We do not "convert" the Python file directly. Instead, we port the **logic**.

1.  **Prototype (Python):** Validate the math.
    *   *Goal:* Define "What is a good squat?" (e.g., `KneeAngle < 90` and `BackAngle > 170`).
2.  **Product (Mobile):** Implement the math using the mobile SDKs.
    *   *Goal:* Run that same check on the phone's GPU in real-time.

## 2. Choosing a Mobile Tech Stack

You have three main options for deployment:

### Option A: Native (Best Performance)
*   **iOS:** Swift + MediaPipe Tasks Vision.
*   **Android:** Kotlin + MediaPipe Tasks Vision.
*   **Pros:** Fastest performance, full access to camera hardware.
*   **Cons:** Two separate codebases to maintain.

### Option B: Cross-Platform (Flutter)
*   **Stack:** Flutter + `google_mlkit_pose_detection` (or MediaPipe Flutter plugin).
*   **Pros:** Single codebase for iOS and Android. Good performance.
*   **Cons:** Slightly more complex setup for native camera streams.

### Option C: Web (Easiest Access)
*   **Stack:** React/Vue + MediaPipe Web (JavaScript).
*   **Pros:** No app store approval needed. Works on any device with a browser.
*   **Cons:** Performance is slightly slower than native apps; requires internet (initially) to load models.

## 3. Code Mapping Example

Here is how the logic translates from Python to a generic Mobile/Swift style.

### Python (Prototype)
```python
# Calculate angle
def calculate_angle(a, b, c):
    # ... math ...
    return angle

# Logic inside the loop
if angle < 90:
    status = "Squatting"
```

### Swift (iOS Production)
```swift
// In your VideoViewController.swift

func didOutput(landmarks: PoseLandmarks) {
    let hip = landmarks.leftHip
    let knee = landmarks.leftKnee
    let ankle = landmarks.leftAnkle
    
    let angle = calculateAngle(a: hip, b: knee, c: ankle)
    
    // UI Update must be on Main Thread
    DispatchQueue.main.async {
        if angle < 90 {
             self.statusLabel.text = "Squatting"
             self.feedbackOverlay.showGreenSuccess()
        }
    }
}
```

## 4. Key Differences to Watch For

1.  **Coordinate Systems:**
    *   **Python (OpenCV):** Often uses pixel coordinates `(x, y)` based on image size (e.g., 640x480).
    *   **MediaPipe Mobile:** Uses normalized coordinates `[0.0, 1.0]` (independent of screen size). *Always use normalized coordinates for math.*

2.  **Threading:**
    *   **Python:** Runs on a single thread (usually).
    *   **Mobile:** Camera runs on a background thread. You must calculate math on the background thread and update UI on the main thread.

3.  **Camera Permissions:**
    *   Mobile apps require explicit user permission to access the camera (info.plist on iOS, AndroidManifest.xml on Android).
