"""
Air Canvas AI
=============
A real-time virtual drawing application using OpenCV and MediaPipe.

Features:
- Track hand landmarks and recognize gestures in real-time.
- DRAW mode (Index finger raised): Draw smooth, anti-aliased lines on a virtual canvas.
- COLOR mode (Index + Middle fingers raised): Cycle through Blue, Green, Red, and Yellow.
- ERASER mode (Closed fist): Erase drawings with a large eraser radius.
- CLEAR mode (Open palm): Clear the virtual canvas with safety hold confirmation.
- Exponential Moving Average (EMA) smoothing to eliminate jitter.
- Clean OpenCV bitwise masking to keep webcam feed bright and drawings crisp.
- Heads-Up Display (HUD) showing mode, color, brush size, FPS, and hand status.
- Keyboard shortcuts: Q (quit), C (clear), S (save), E (eraser toggle), F (fullscreen), 1-4 (colors).
"""

import os
import sys
import time
from datetime import datetime
import cv2
import mediapipe as mp
import numpy as np


# =====================================================================
# Configuration & Constants
# =====================================================================

# Color Palette (OpenCV uses BGR format)
PALETTE = [
    {"name": "BLUE", "bgr": (255, 0, 0), "rgb": (0, 0, 255)},
    {"name": "GREEN", "bgr": (0, 255, 0), "rgb": (0, 255, 0)},
    {"name": "RED", "bgr": (0, 0, 255), "rgb": (255, 0, 0)},
    {"name": "YELLOW", "bgr": (0, 255, 255), "rgb": (255, 255, 0)},
]

# Drawing Parameters
DEFAULT_BRUSH_SIZE = 8
ERASER_RADIUS = 40
SMOOTHING_ALPHA = 0.55  # 0.0 = previous point only, 1.0 = raw point (no smoothing)
CLEAR_HOLD_FRAMES = 12   # Require holding open palm for ~0.4s to prevent accidental clear
COLOR_CYCLE_COOLDOWN = 0.7  # Seconds between automatic color cycles when holding gesture

# Directory to save drawings
OUTPUT_DIR = "drawings"


# =====================================================================
# Hand Landmark & Gesture Analysis
# =====================================================================

def detect_finger_states(landmarks, hand_label):
    """
    Analyzes the 21 MediaPipe hand landmarks to determine which fingers are raised.

    Parameters:
        landmarks: MediaPipe normalized hand landmarks list (21 points).
        hand_label (str): "Left" or "Right" classification.

    Returns:
        dict: Boolean status for each finger ('Thumb', 'Index', 'Middle', 'Ring', 'Pinky').
    """
    finger_status = {
        "Thumb": False,
        "Index": False,
        "Middle": False,
        "Ring": False,
        "Pinky": False,
    }

    # 1. Thumb Check
    # In mirrored webcam view:
    # - Right hand: Thumb tip extends towards screen-left (smaller X than IP joint)
    # - Left hand: Thumb tip extends towards screen-right (larger X than IP joint)
    thumb_tip = landmarks[4]
    thumb_ip = landmarks[3]
    if hand_label == "Right":
        finger_status["Thumb"] = thumb_tip.x < thumb_ip.x
    else:
        finger_status["Thumb"] = thumb_tip.x > thumb_ip.x

    # 2. Four Fingers (Index, Middle, Ring, Pinky)
    # A finger is raised if its tip Y-coordinate is higher (smaller value) than its PIP joint.
    finger_indices = [
        ("Index", 8, 6),
        ("Middle", 12, 10),
        ("Ring", 16, 14),
        ("Pinky", 20, 18),
    ]

    for name, tip_idx, pip_idx in finger_indices:
        finger_status[name] = landmarks[tip_idx].y < landmarks[pip_idx].y

    return finger_status


def classify_gesture(finger_status):
    """
    Classifies the current hand gesture based on finger states.

    Gestures:
    - Index finger only -> DRAW
    - Index + Middle fingers -> COLOR
    - Closed fist (all 4 fingers down) -> ERASER
    - Open palm (all 4 fingers up) -> CLEAR
    - Any other combination -> STANDBY
    """
    idx = finger_status["Index"]
    mid = finger_status["Middle"]
    rng = finger_status["Ring"]
    pnk = finger_status["Pinky"]

    # Open Palm: all 4 fingers raised (and thumb usually out)
    if idx and mid and rng and pnk:
        return "CLEAR"

    # Closed Fist: all 4 fingers curled down
    if not idx and not mid and not rng and not pnk:
        return "ERASER"

    # Index + Middle only: COLOR selection mode
    if idx and mid and not rng and not pnk:
        return "COLOR"

    # Index only: DRAW mode
    if idx and not mid and not rng and not pnk:
        return "DRAW"

    return "STANDBY"


# =====================================================================
# Canvas & Drawing Operations
# =====================================================================

def smooth_point(prev_point, curr_raw, alpha=SMOOTHING_ALPHA):
    """
    Applies Exponential Moving Average (EMA) smoothing to reduce fingertip jitter.

    Parameters:
        prev_point (tuple or None): Previous (x, y) coordinates.
        curr_raw (tuple): Current raw (x, y) coordinates.
        alpha (float): Smoothing weight (0 < alpha <= 1).

    Returns:
        tuple: Smoothed (x, y) coordinates.
    """
    if prev_point is None:
        return curr_raw
    smoothed_x = int(alpha * curr_raw[0] + (1.0 - alpha) * prev_point[0])
    smoothed_y = int(alpha * curr_raw[1] + (1.0 - alpha) * prev_point[1])
    return (smoothed_x, smoothed_y)


def blend_canvas(frame, canvas):
    """
    Combines the drawing canvas with the webcam feed using bitwise masking.

    Ensures drawings are 100% opaque and vibrant without dimming or discoloring
    the live camera background.

    Parameters:
        frame (np.ndarray): Mirrored webcam BGR frame.
        canvas (np.ndarray): Virtual canvas BGR array (black background).

    Returns:
        np.ndarray: Blended output frame.
    """
    # 1. Convert canvas to grayscale
    canvas_gray = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY)

    # 2. Create binary mask of the drawing (non-black pixels = drawing)
    _, mask = cv2.threshold(canvas_gray, 10, 255, cv2.THRESH_BINARY)

    # 3. Create inverse mask to cut out drawing silhouette from webcam feed
    inv_mask = cv2.bitwise_not(mask)

    # 4. Black out drawing region on the webcam frame
    frame_bg = cv2.bitwise_and(frame, frame, mask=inv_mask)

    # 5. Extract only the colored strokes from the canvas
    canvas_fg = cv2.bitwise_and(canvas, canvas, mask=mask)

    # 6. Add together to produce clean composite
    return cv2.add(frame_bg, canvas_fg)


def save_drawing(frame, canvas):
    """
    Saves the current drawing composite to disk with a timestamp.

    Parameters:
        frame (np.ndarray): Clean webcam frame.
        canvas (np.ndarray): Drawing canvas.

    Returns:
        str: Path of the saved image file.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"drawing_{timestamp}.png"
    filepath = os.path.join(OUTPUT_DIR, filename)

    # Create composite frame without HUD elements
    composite = blend_canvas(frame, canvas)
    cv2.imwrite(filepath, composite)
    return filepath


# =====================================================================
# UI & HUD Rendering
# =====================================================================

def draw_hud(frame, mode, color_info, brush_size, fps, hand_detected, toast_message=""):
    """
    Renders a modern, semi-transparent Heads-Up Display (HUD) in the top-left corner.
    """
    h, w, _ = frame.shape
    card_w = 260
    card_h = 160

    # Create semi-transparent card overlay
    overlay = frame.copy()
    cv2.rectangle(overlay, (15, 15), (15 + card_w, 15 + card_h), (25, 25, 25), -1)
    cv2.addWeighted(overlay, 0.70, frame, 0.30, 0, frame)

    # Border around card
    cv2.rectangle(frame, (15, 15), (15 + card_w, 15 + card_h), (80, 80, 80), 1)

    # 1. Title
    cv2.putText(
        frame,
        "AIR CANVAS AI",
        (30, 42),
        cv2.FONT_HERSHEY_DUPLEX,
        0.70,
        (0, 215, 255),
        2,
        cv2.LINE_AA,
    )

    # Mode accent colors
    mode_colors = {
        "DRAW": (0, 255, 0),       # Green
        "COLOR": (255, 0, 255),    # Magenta
        "ERASER": (0, 165, 255),   # Orange
        "CLEAR": (0, 0, 255),      # Red
        "STANDBY": (180, 180, 180) # Gray
    }
    mode_bgr = mode_colors.get(mode, (200, 200, 200))

    # 2. Mode
    cv2.putText(
        frame,
        f"Mode: {mode}",
        (30, 68),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        mode_bgr,
        2,
        cv2.LINE_AA,
    )

    # 3. Color Display with Color Swatch Box
    cv2.putText(
        frame,
        f"Color: {color_info['name']}",
        (30, 92),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    # Color swatch square
    cv2.rectangle(frame, (165, 78), (185, 96), color_info["bgr"], -1)
    cv2.rectangle(frame, (165, 78), (185, 96), (255, 255, 255), 1)

    # 4. Brush Size
    effective_size = ERASER_RADIUS if mode == "ERASER" else brush_size
    cv2.putText(
        frame,
        f"Brush Size: {effective_size}",
        (30, 116),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )

    # 5. FPS & Hand Detection status
    hand_text = "YES" if hand_detected else "NO"
    hand_color = (0, 255, 0) if hand_detected else (0, 0, 255)
    cv2.putText(
        frame,
        f"FPS: {int(fps)}",
        (30, 140),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.50,
        (200, 200, 200),
        1,
        cv2.LINE_AA,
    )
    cv2.putText(
        frame,
        f"Hand: {hand_text}",
        (120, 140),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.50,
        hand_color,
        2,
        cv2.LINE_AA,
    )

    # 6. Bottom Shortcut Bar
    shortcut_text = "Q:Quit | C:Clear | S:Save | E:Eraser | F:Fullscreen | 1-4:Color"
    cv2.putText(
        frame,
        shortcut_text,
        (20, h - 15),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        (200, 200, 200),
        1,
        cv2.LINE_AA,
    )

    # 7. Toast Notification (e.g. "Drawing Saved!", "Canvas Cleared!")
    if toast_message:
        (tw, th), _ = cv2.getTextSize(toast_message, cv2.FONT_HERSHEY_SIMPLEX, 0.65, 2)
        cx = w // 2
        cy = 50
        cv2.rectangle(
            frame,
            (cx - tw // 2 - 15, cy - th - 10),
            (cx + tw // 2 + 15, cy + 10),
            (30, 30, 30),
            -1,
        )
        cv2.rectangle(
            frame,
            (cx - tw // 2 - 15, cy - th - 10),
            (cx + tw // 2 + 15, cy + 10),
            (0, 215, 255),
            2,
        )
        cv2.putText(
            frame,
            toast_message,
            (cx - tw // 2, cy),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )


def draw_cursor(frame, mode, point, color_bgr, brush_size, clear_progress=0.0):
    """
    Renders dynamic visual feedback on the user's active fingertip/knuckle.
    """
    if point is None:
        return

    x, y = point

    if mode == "DRAW":
        # Solid circle with white outer ring showing brush size & color
        cv2.circle(frame, (x, y), brush_size, color_bgr, -1, cv2.LINE_AA)
        cv2.circle(frame, (x, y), brush_size + 3, (255, 255, 255), 1, cv2.LINE_AA)

    elif mode == "COLOR":
        # Target circle indicating color selection mode
        cv2.circle(frame, (x, y), 14, color_bgr, 2, cv2.LINE_AA)
        cv2.circle(frame, (x, y), 5, (255, 255, 255), -1, cv2.LINE_AA)

    elif mode == "ERASER":
        # Large dashed/double circle showing the eraser boundary
        cv2.circle(frame, (x, y), ERASER_RADIUS, (0, 165, 255), 2, cv2.LINE_AA)
        cv2.circle(frame, (x, y), 4, (0, 165, 255), -1, cv2.LINE_AA)

    elif mode == "CLEAR":
        # Circular progress ring when holding open palm
        cv2.circle(frame, (x, y), 25, (0, 0, 255), 2, cv2.LINE_AA)
        if clear_progress > 0:
            axes = (25, 25)
            angle = -90
            end_angle = int(-90 + 360 * clear_progress)
            cv2.ellipse(frame, (x, y), axes, 0, angle, end_angle, (0, 255, 255), 4, cv2.LINE_AA)


# =====================================================================
# Main Application Loop
# =====================================================================

def main():
    print("=" * 60)
    print(" Air Canvas AI (OpenCV + MediaPipe)")
    print("=" * 60)
    print("Initializing webcam...")

    # 1. Initialize Webcam with fallback support
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[WARNING] Could not open camera at index 0. Trying camera index 1...")
        cap = cv2.VideoCapture(1)

    if not cap.isOpened():
        print("\n[ERROR] Unable to access any webcam.")
        print("Please check that:")
        print("  1. Your webcam is connected.")
        print("  2. Other applications (Teams, Zoom, browser) are not locking it.")
        print("  3. Windows camera privacy settings allow desktop apps to access the camera.")
        sys.exit(1)

    # Set camera resolution (640x480 for smooth 30+ FPS real-time processing)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    # 2. Initialize MediaPipe Hands
    mp_hands = mp.solutions.hands
    mp_drawing = mp.solutions.drawing_utils

    landmark_style = mp_drawing.DrawingSpec(color=(0, 255, 128), thickness=2, circle_radius=2)
    connection_style = mp_drawing.DrawingSpec(color=(220, 220, 220), thickness=1)

    hands = mp_hands.Hands(
        static_image_mode=False,
        max_num_hands=1,              # Track primary drawing hand for optimal focus
        min_detection_confidence=0.7,
        min_tracking_confidence=0.5,
    )

    # Application State
    color_index = 0                   # Start with BLUE
    brush_size = DEFAULT_BRUSH_SIZE
    prev_draw_point = None
    prev_mode = "STANDBY"
    is_eraser_toggled = False         # Keyboard toggle for eraser
    is_fullscreen = False             # Fullscreen toggle state
    clear_frame_count = 0             # Counter for clear gesture hold confirmation
    last_color_cycle_time = 0.0

    # Toast notification state
    toast_message = ""
    toast_expire_time = 0.0

    # FPS Calculation
    prev_time = time.time()
    fps = 0.0

    # Virtual Canvas (initialized lazily upon reading first frame to match resolution)
    canvas = None

    # Setup OpenCV Window
    window_name = "Air Canvas AI"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    print("\nWebcam ready!")
    print("Controls:")
    print("  - Index Finger Only:        DRAW")
    print("  - Index + Middle Fingers:   COLOR (Cycles Blue, Green, Red, Yellow)")
    print("  - Closed Fist:              ERASER (Large radius)")
    print("  - Open Palm:                CLEAR canvas")
    print("  - Keyboard 'S':             Save drawing to 'drawings/' folder")
    print("  - Keyboard 'C':             Clear canvas")
    print("  - Keyboard 'E':             Toggle eraser mode")
    print("  - Keyboard 'F':             Toggle fullscreen mode")
    print("  - Keyboard '1'-'4':         Select Blue, Green, Red, Yellow")
    print("  - Keyboard 'Q':             Quit application\n")

    try:
        while True:
            success, frame = cap.read()
            if not success or frame is None:
                print("[WARNING] Failed to grab frame. Retrying...")
                time.sleep(0.01)
                continue

            # Mirror the frame horizontally for natural selfie drawing
            frame = cv2.flip(frame, 1)
            h, w, _ = frame.shape

            # Initialize canvas if not yet created or if resolution changed
            if canvas is None or canvas.shape != frame.shape:
                canvas = np.zeros_like(frame)

            # Calculate FPS
            curr_time = time.time()
            fps = 0.9 * fps + 0.1 * (1.0 / (curr_time - prev_time)) if (curr_time - prev_time) > 0 else fps
            prev_time = curr_time

            # Clear toast if expired
            if toast_message and curr_time > toast_expire_time:
                toast_message = ""

            # Process Hand Landmarks with MediaPipe
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = hands.process(rgb_frame)

            hand_detected = False
            active_point = None
            raw_mode = "STANDBY"
            clear_progress = 0.0

            if results.multi_hand_landmarks and results.multi_handedness:
                hand_detected = True
                hand_landmarks = results.multi_hand_landmarks[0]
                handedness = results.multi_handedness[0]
                hand_label = handedness.classification[0].label

                # 1. Analyze finger states
                finger_status = detect_finger_states(hand_landmarks.landmark, hand_label)
                raw_mode = classify_gesture(finger_status)

                # 2. Extract key landmark points in pixel coordinates
                # Landmark 8: Index fingertip
                index_tip_raw = (
                    int(hand_landmarks.landmark[8].x * w),
                    int(hand_landmarks.landmark[8].y * h),
                )
                # Landmark 9: Middle MCP (knuckle / fist center for eraser)
                fist_center_raw = (
                    int(hand_landmarks.landmark[9].x * w),
                    int(hand_landmarks.landmark[9].y * h),
                )

                # 3. Handle Keyboard Eraser Override
                if is_eraser_toggled and raw_mode == "DRAW":
                    current_mode = "ERASER"
                    active_point = index_tip_raw
                else:
                    current_mode = raw_mode
                    if current_mode == "ERASER":
                        active_point = fist_center_raw
                    else:
                        active_point = index_tip_raw

                # 4. Mode-specific Logic
                if current_mode == "COLOR":
                    prev_draw_point = None
                    clear_frame_count = 0
                    # Cycle color on initial gesture entrance OR when held with cooldown
                    if prev_mode != "COLOR" or (curr_time - last_color_cycle_time) > COLOR_CYCLE_COOLDOWN:
                        color_index = (color_index + 1) % len(PALETTE)
                        last_color_cycle_time = curr_time
                        is_eraser_toggled = False
                        toast_message = f"Selected: {PALETTE[color_index]['name']}"
                        toast_expire_time = curr_time + 1.2

                elif current_mode == "CLEAR":
                    prev_draw_point = None
                    clear_frame_count += 1
                    clear_progress = min(1.0, clear_frame_count / CLEAR_HOLD_FRAMES)
                    if clear_frame_count >= CLEAR_HOLD_FRAMES:
                        canvas = np.zeros_like(frame)
                        toast_message = "Canvas Cleared!"
                        toast_expire_time = curr_time + 1.5
                        clear_frame_count = 0

                elif current_mode == "DRAW":
                    clear_frame_count = 0
                    current_bgr = PALETTE[color_index]["bgr"]
                    # Apply smoothing to reduce jitter
                    smoothed = smooth_point(prev_draw_point, active_point)

                    if prev_draw_point is not None:
                        # Draw smooth line segment on virtual canvas
                        cv2.line(canvas, prev_draw_point, smoothed, current_bgr, brush_size, cv2.LINE_AA)
                        cv2.circle(canvas, smoothed, brush_size // 2, current_bgr, -1, cv2.LINE_AA)

                    prev_draw_point = smoothed
                    active_point = smoothed

                elif current_mode == "ERASER":
                    clear_frame_count = 0
                    # Erase on virtual canvas by drawing filled black circle
                    smoothed = smooth_point(prev_draw_point, active_point, alpha=0.7)
                    cv2.circle(canvas, smoothed, ERASER_RADIUS, (0, 0, 0), -1)
                    prev_draw_point = smoothed
                    active_point = smoothed

                else:  # STANDBY
                    prev_draw_point = None
                    clear_frame_count = 0

                prev_mode = current_mode

                # Optional: draw skeletal landmarks lightly on frame
                mp_drawing.draw_landmarks(
                    frame,
                    hand_landmarks,
                    mp_hands.HAND_CONNECTIONS,
                    landmark_drawing_spec=landmark_style,
                    connection_drawing_spec=connection_style,
                )

            else:
                # Hand lost: reset drawing stroke so re-entering doesn't create connecting line
                prev_draw_point = None
                clear_frame_count = 0
                prev_mode = "STANDBY"
                current_mode = "ERASER" if is_eraser_toggled else "STANDBY"

            # 5. Composite Drawing Canvas with Camera Feed
            blended_frame = blend_canvas(frame, canvas)

            # 6. Draw dynamic fingertip cursor / eraser boundary
            if hand_detected and active_point is not None:
                current_bgr = PALETTE[color_index]["bgr"]
                draw_cursor(
                    blended_frame,
                    current_mode,
                    active_point,
                    current_bgr,
                    brush_size,
                    clear_progress=clear_progress,
                )

            # 7. Render Heads-Up Display (HUD)
            draw_hud(
                blended_frame,
                current_mode,
                PALETTE[color_index],
                brush_size,
                fps,
                hand_detected,
                toast_message=toast_message,
            )

            # 8. Display output window
            cv2.imshow(window_name, blended_frame)

            # 9. Handle Keyboard Controls & Window Close
            key = cv2.waitKey(1) & 0xFF
            if key in (ord('q'), ord('Q'), 27) or cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                print("\nQuit signal received. Exiting...")
                break

            elif key in (ord('c'), ord('C')):    # Clear canvas
                canvas = np.zeros_like(frame)
                toast_message = "Canvas Cleared!"
                toast_expire_time = curr_time + 1.5

            elif key in (ord('s'), ord('S')):    # Save drawing
                filepath = save_drawing(frame, canvas)
                toast_message = f"Saved: {os.path.basename(filepath)}"
                toast_expire_time = curr_time + 2.5
                print(f"[INFO] Drawing successfully saved to {filepath}")

            elif key in (ord('e'), ord('E')):    # Toggle eraser
                is_eraser_toggled = not is_eraser_toggled
                status_str = "ON" if is_eraser_toggled else "OFF"
                toast_message = f"Eraser: {status_str}"
                toast_expire_time = curr_time + 1.5

            elif key in (ord('f'), ord('F')):    # Toggle fullscreen
                is_fullscreen = not is_fullscreen
                if is_fullscreen:
                    cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
                    toast_message = "Fullscreen: ON"
                else:
                    cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_NORMAL)
                    toast_message = "Fullscreen: OFF"
                toast_expire_time = curr_time + 1.5

            elif key == ord('1'):                # Blue
                color_index = 0
                is_eraser_toggled = False
                toast_message = "Color: BLUE"
                toast_expire_time = curr_time + 1.2

            elif key == ord('2'):                # Green
                color_index = 1
                is_eraser_toggled = False
                toast_message = "Color: GREEN"
                toast_expire_time = curr_time + 1.2

            elif key == ord('3'):                # Red
                color_index = 2
                is_eraser_toggled = False
                toast_message = "Color: RED"
                toast_expire_time = curr_time + 1.2

            elif key == ord('4'):                # Yellow
                color_index = 3
                is_eraser_toggled = False
                toast_message = "Color: YELLOW"
                toast_expire_time = curr_time + 1.2

    except KeyboardInterrupt:
        print("\nInterrupted by user. Exiting...")
    finally:
        cap.release()
        cv2.destroyAllWindows()
        hands.close()
        print("Resources released cleanly. Goodbye!")


if __name__ == "__main__":
    main()
