# UX/UI Strategy: Mobile Rehabilitation App

## 1. Design Philosophy: "Clarity over Data"
For a non-medical rehabilitation app, the user is likely in pain, recovering, or has limited mobility. The interface must be **large, simple, and forgiving**. Avoid technical graphs; focus on encouragement and clear, large visual cues.

## 2. Key User Flows

### Flow A: The "Daily Routine" (Primary Loop)
1.  **Home Screen:** Shows *one* primary call-to-action: "Start Today's Session".
2.  **Setup Guide:** A quick 5-second check: "Can we see your whole body?" (User steps back until outline turns green).
3.  **Exercise Session:** Large camera view with minimal overlay.
4.  **Summary:** "Great job! You did 10 squats." (Confetti/Success sound).

### Flow B: Setup/Calibration
*   **Voice Guidance:** "Place your phone on the floor against a wall."
*   **Visual Silhouette:** A ghost overlay on the camera feed showing the user where to stand.

## 3. UI Component Breakdown

### A. The "Smart Mirror" Interface (Exercise View)
This is the core screen. It should look like a clean camera viewfinder but with "Augmented Reality" (AR) elements.
*   **The Skeleton Overlay:**
    *   *Don't* show the full scary robot skeleton.
    *   *Do* show simplified "Connectors" on the limbs being worked (e.g., just the leg lines for squats).
    *   **Color Coding:** White = Neutral, Green = Good Form, Red = Correction Needed.
*   **The "Rep Counter":**
    *   Huge typography in the top center (e.g., "5 / 10").
    *   Pulses or grows slightly when a rep is completed.
*   **Feedback Pill:**
    *   A large pill-shaped notification at the bottom.
    *   *Text:* "Go Lower", "Keep Back Straight", "Perfect!".
    *   *Audio:* Text-to-speech reads this out loud so the user doesn't have to squint.

### B. The "Progress Rings" (Home Screen)
Taking inspiration from Apple Fitness:
*   **Daily Goal:** A simple ring that fills up as they complete their minutes/reps.
*   **Streak Counter:** "3 Day Streak" (Motivation).
*   **Pain Tracker:** A simple slider (0-10) pop-up *after* the workout: "How does your knee feel?"

## 4. Accessibility Considerations (Critical)
*   **Voice Control:** "Pause" or "Stop" voice commands so users don't have to walk back to the phone mid-exercise.
*   **High Contrast:** Use bold colors (Dark Mode with Neon Green/Orange) for visibility at a distance (6-8 feet away).
*   **Large Touch Targets:** Buttons should be full-width or at least 60px height.

## 5. Mockup Descriptions

### Screen 1: "Get Ready"
*   **Visual:** Illustration of a phone leaning against a water bottle or wall.
*   **Text:** "Place phone on floor. Step back 6 feet."
*   **Button:** "I'm Ready" (Big Green Button).

### Screen 2: "The Session"
*   **Background:** Live Camera Feed.
*   **Overlay:** 
    *   Top Left: Time Remaining (03:00).
    *   Top Center: **05** (Reps).
    *   Center: User's body with *Green* lines on legs.
    *   Bottom Center: "Good Depth!" (Fading text).

### Screen 3: "Session Complete"
*   **Visual:** Big Checkmark Animation.
*   **Stats:** "15 Reps • 85% Accuracy".
*   **Action:** "Finish" or "Next Exercise".
