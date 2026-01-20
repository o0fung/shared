# Rehabilitation Product Strategy & Plan

## 1. Executive Summary
This document outlines a strategic plan to build profitable, algorithm-driven rehabilitation software using off-the-shelf commercial hardware. The goal is to democratize access to physical therapy (PT) and rehabilitation by leveraging consumer devices (webcams, smartphones, smartwatches) combined with advanced computer vision and machine learning algorithms.

## 2. Market Opportunity
*   **Problem:** Traditional physical therapy is expensive, requires travel, and lacks objective data tracking between sessions. Patient adherence to home exercise programs is typically low.
*   **Solution:** A digital health platform that uses existing devices to guide, monitor, and gamify rehabilitation exercises at home.
*   **Trends:** Telehealth expansion, advancements in edge AI (on-device processing), and increasing adoption of wearables.

## 3. Technology Stack (Off-the-Shelf)

### A. Hardware
We will strictly avoid custom hardware manufacturing to minimize capital expenditure.
*   **Vision Input:** Standard Laptops/Webcams, Smartphone Cameras.
*   **Sensor Input:** 
    *   **Smartphones:** Accelerometer, Gyroscope (IMU).
    *   **Wearables:** Apple Watch, WearOS devices (for wrist motion tracking).
    *   **IoT:** Nintendo Ring Fit or similar low-cost Bluetooth peripherals (optional).

### B. Software & Algorithms
*   **Computer Vision:** 
    *   **Google MediaPipe:** For real-time high-fidelity body pose, hand, and face tracking on mobile/web.
    *   **OpenCV:** For basic image processing.
*   **Machine Learning:**
    *   **TensorFlow Lite / ONNX Runtime:** For running classification models on user devices (Edge AI) to ensure privacy (HIPAA compliance) and low latency.
    *   **Algorithms:**
        *   **Dynamic Time Warping (DTW):** To compare a patient's movement curve against a "gold standard" reference motion.
        *   **Pose Classification:** To detect specific exercises (e.g., "Squat" vs "Lunge").
        *   **ROM Calculation:** Geometric algorithms to calculate Range of Motion angles in real-time.

## 4. Proposed Product Concepts

### Concept A: "VisionPT" - AI-Powered Remote Physical Therapy Assistant
*   **Description:** A web/mobile app where the camera tracks the user performing prescribed exercises.
*   **Core Feature:** Real-time visual feedback overlay (green lines for correct posture, red for incorrect).
*   **Algorithm:** MediaPipe Pose Landmark detection -> Angle calculation -> Comparison with therapist-defined thresholds.
*   **Target:** Post-op orthopedic patients (knee, shoulder).

### Concept B: "NeuroGrasp" - Fine Motor Skills via Mobile
*   **Description:** Uses the smartphone camera (hand tracking) or screen interaction to rehabilitate fine motor skills.
*   **Core Feature:** Games that require precise finger pinching, tracing, or gripping.
*   **Algorithm:** MediaPipe Hands for 21-point hand skeleton tracking.
*   **Target:** Stroke survivors, Arthritis patients.

## 5. Technical Feasibility & FAQs

### Do we need Depth Sensors (LiDAR/Kinect)?
**No.** While depth sensors provide absolute distance measurements, they are not required for most rehabilitation use cases.
*   **Why?** MediaPipe is trained to infer 3D coordinates ($x, y, z$) from a single 2D RGB camera. The "Z" coordinate represents relative depth.
*   **Benefit:** This allows your product to run on billions of existing cheap Android/iOS devices and laptops, rather than just high-end iPad Pros with LiDAR.

### Can we prototype in Python and move to Mobile?
**Yes.** This is the standard industry workflow.
*   **Prototyping (Python):** Rapidly test math, angles, and "rehab logic" (e.g., "Is the knee bent at 90 degrees?"). Python is faster to write and debug.
*   **Production (Mobile):** Once the *math* is proven, you port just the logic to the mobile app.
    *   **Android:** MediaPipe offers a Java/Kotlin API.
    *   **iOS:** MediaPipe offers an Objective-C/Swift API.
    *   **Cross-Platform:** You can use **Flutter** or **React Native** (with some native bridges) or **TensorFlow.js** for web-based mobile apps.

## 6. Monetization Strategy
*   **B2B (Clinics):** "Provider Dashboard" subscription. Therapists pay to prescribe exercises and view patient data/compliance.
    *   *Price:* $50-100/month per therapist.
*   **B2C (Direct to Patient):** Freemium model. Basic exercises free; personalized AI coaching and history analytics for a monthly fee.
    *   *Price:* $9.99/month.
*   **Data Licensing:** Aggregated, anonymized kinematic data is valuable for research and insurance companies.

## 7. Implementation Roadmap

### Phase 1: Prototype (Weeks 1-4)
*   **Objective:** Proof of concept for VisionPT.
*   **Tech:** Python script using OpenCV and MediaPipe.
*   **Output:** A script that detects a squat and counts repetitions based on knee angle.

### Phase 2: MVP Development (Weeks 5-12)
*   **Objective:** Mobile-accessible web app.
*   **Tech:** React (Frontend) + TensorFlow.js (In-browser ML).
*   **Features:** User login, 3 standard exercises, real-time feedback.

### Phase 3: Pilot & Iterate (Weeks 13-16)
*   **Objective:** User testing.
*   **Action:** Deploy to 10 beta testers. Collect feedback on UI/UX and detection accuracy.

## 8. Next Steps for Development
1.  Initialize a Python environment for the Phase 1 prototype.
2.  Implement a basic "Squat Counter" using MediaPipe.
3.  Set up a basic web interface to visualize the camera feed and overlay.
