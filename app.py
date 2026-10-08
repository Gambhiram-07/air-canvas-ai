"""
Air Canvas AI — Streamlit Web Application
==========================================
Deployable to Hugging Face Spaces, Streamlit Community Cloud, or any web server.
Uses WebRTC for real-time in-browser video streaming and MediaPipe for touchless drawing.
"""

import threading
import time
from datetime import datetime
import av
import cv2
import mediapipe as mp
import numpy as np
import streamlit as st
from streamlit_webrtc import (
    ClientSettings,
    RTCConfiguration,
    VideoProcessorBase,
    WebRtcMode,
    webrtc_streamer,
)

# -----------------------------------------------------------------------------
# App Configuration & Page Layout
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Air Canvas AI — Touchless Drawing",
    page_icon="🖐️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Color Palette definition (BGR format for OpenCV)
PALETTE = [
    {"name": "BLUE", "bgr": (255, 0, 0), "hex": "#0000FF"},
    {"name": "GREEN", "bgr": (0, 255, 0), "hex": "#00FF00"},
    {"name": "RED", "bgr": (0, 0, 255), "hex": "#FF0000"},
    {"name": "YELLOW", "bgr": (0, 255, 255), "hex": "#FFFF00"},
]

# STUN servers for reliable WebRTC NAT traversal across public networks
RTC_CONFIG = RTCConfiguration(
    {"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]}
)


# -----------------------------------------------------------------------------
# Core Gesture & Drawing Helper Functions
# -----------------------------------------------------------------------------
def detect_finger_states(landmarks, hand_label):
    """Detect whether each finger is raised or curled."""
    finger_status = {
        "Thumb": False,
        "Index": False,
        "Middle": False,
        "Ring": False,
        "Pinky": False,
    }

    thumb_tip = landmarks[4]
    thumb_ip = landmarks[3]
    if hand_label == "Right":
        finger_status["Thumb"] = thumb_tip.x < thumb_ip.x
    else:
        finger_status["Thumb"] = thumb_tip.x > thumb_ip.x

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
    """Classify hand gesture based on finger states."""
    idx = finger_status["Index"]
    mid = finger_status["Middle"]
    rng = finger_status["Ring"]
    pnk = finger_status["Pinky"]

    if idx and mid and rng and pnk:
        return "CLEAR"
    if not idx and not mid and not rng and not pnk:
        return "ERASER"
    if idx and mid and not rng and not pnk:
        return "COLOR"
    if idx and not mid and not rng and not pnk:
        return "DRAW"
    return "STANDBY"


def smooth_point(prev_point, curr_raw, alpha=0.55):
    """Exponential Moving Average (EMA) coordinate smoothing."""
    if prev_point is None:
        return curr_raw
    smoothed_x = int(alpha * curr_raw[0] + (1.0 - alpha) * prev_point[0])
    smoothed_y = int(alpha * curr_raw[1] + (1.0 - alpha) * prev_point[1])
    return (smoothed_x, smoothed_y)


def blend_canvas(frame, canvas, white_canvas_mode=False):
    """Bitwise masking to blend virtual canvas with camera frame or digital whiteboard."""
    canvas_gray = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(canvas_gray, 10, 255, cv2.THRESH_BINARY)
    inv_mask = cv2.bitwise_not(mask)

    if white_canvas_mode:
        background = np.full_like(frame, 255)
    else:
        background = frame

    frame_bg = cv2.bitwise_and(background, background, mask=inv_mask)
    canvas_fg = cv2.bitwise_and(canvas, canvas, mask=mask)
    return cv2.add(frame_bg, canvas_fg)


# -----------------------------------------------------------------------------
# WebRTC Video Processor Class
# -----------------------------------------------------------------------------
class AirCanvasProcessor(VideoProcessorBase):
    def __init__(self):
        self.lock = threading.Lock()
        self.canvas = None
        self.color_index = 0
        self.brush_size = 8
        self.eraser_radius = 40
        self.smoothing_alpha = 0.55
        self.white_canvas_mode = False
        self.clear_requested = False

        self.prev_draw_point = None
        self.prev_mode = "STANDBY"
        self.clear_frame_count = 0
        self.last_color_cycle_time = 0.0
        self.prev_time = time.time()
        self.fps = 0.0

        # Initialize MediaPipe Hands
        self.mp_hands = mp.solutions.hands
        self.mp_drawing = mp.solutions.drawing_utils
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            min_detection_confidence=0.7,
            min_tracking_confidence=0.5,
        )
        self.landmark_style = self.mp_drawing.DrawingSpec(
            color=(0, 255, 128), thickness=2, circle_radius=2
        )
        self.connection_style = self.mp_drawing.DrawingSpec(
            color=(220, 220, 220), thickness=1
        )

    def recv(self, frame: av.VideoFrame) -> av.VideoFrame:
        img = frame.to_ndarray(format="bgr24")
        img = cv2.flip(img, 1)  # Mirror for natural interaction
        h, w, _ = img.shape

        with self.lock:
            # Initialize or resize virtual canvas
            if self.canvas is None or self.canvas.shape != img.shape:
                self.canvas = np.zeros_like(img)

            if self.clear_requested:
                self.canvas = np.zeros_like(img)
                self.clear_requested = False

            # Calculate FPS
            now = time.time()
            dt = now - self.prev_time
            if dt > 0:
                self.fps = 0.9 * self.fps + 0.1 * (1.0 / dt)
            self.prev_time = now

            # Process MediaPipe Landmarks
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            results = self.hands.process(rgb)

            current_mode = "STANDBY"
            clear_progress = 0.0

            if results.multi_hand_landmarks and results.multi_handedness:
                hand_landmarks = results.multi_hand_landmarks[0]
                handedness = results.multi_handedness[0]
                hand_label = handedness.classification[0].label

                finger_status = detect_finger_states(hand_landmarks.landmark, hand_label)
                raw_mode = classify_gesture(finger_status)
                current_mode = raw_mode

                index_tip_raw = (
                    int(hand_landmarks.landmark[8].x * w),
                    int(hand_landmarks.landmark[8].y * h),
                )
                fist_center_raw = (
                    int(hand_landmarks.landmark[9].x * w),
                    int(hand_landmarks.landmark[9].y * h),
                )

                if current_mode == "COLOR":
                    self.prev_draw_point = None
                    self.clear_frame_count = 0
                    if self.prev_mode != "COLOR" or (now - self.last_color_cycle_time) > 0.7:
                        self.color_index = (self.color_index + 1) % len(PALETTE)
                        self.last_color_cycle_time = now

                elif current_mode == "CLEAR":
                    self.prev_draw_point = None
                    self.clear_frame_count += 1
                    clear_progress = min(1.0, self.clear_frame_count / 12)
                    if self.clear_frame_count >= 12:
                        self.canvas = np.zeros_like(img)
                        self.clear_frame_count = 0

                elif current_mode == "DRAW":
                    self.clear_frame_count = 0
                    current_bgr = PALETTE[self.color_index]["bgr"]
                    smoothed = smooth_point(
                        self.prev_draw_point, index_tip_raw, alpha=self.smoothing_alpha
                    )
                    if self.prev_draw_point is not None:
                        cv2.line(
                            self.canvas,
                            self.prev_draw_point,
                            smoothed,
                            current_bgr,
                            self.brush_size,
                            cv2.LINE_AA,
                        )
                        cv2.circle(
                            self.canvas,
                            smoothed,
                            self.brush_size // 2,
                            current_bgr,
                            -1,
                            cv2.LINE_AA,
                        )
                    self.prev_draw_point = smoothed

                elif current_mode == "ERASER":
                    self.clear_frame_count = 0
                    smoothed = smooth_point(
                        self.prev_draw_point, fist_center_raw, alpha=0.7
                    )
                    cv2.circle(
                        self.canvas,
                        smoothed,
                        self.eraser_radius,
                        (0, 0, 0),
                        -1,
                    )
                    self.prev_draw_point = smoothed
                else:
                    self.prev_draw_point = None
                    self.clear_frame_count = 0

                self.prev_mode = current_mode

                # Draw skeletal landmarks lightly
                self.mp_drawing.draw_landmarks(
                    img,
                    hand_landmarks,
                    self.mp_hands.HAND_CONNECTIONS,
                    landmark_drawing_spec=self.landmark_style,
                    connection_drawing_spec=self.connection_style,
                )
            else:
                self.prev_draw_point = None
                self.clear_frame_count = 0

            # Composite the drawing and camera feed
            output = blend_canvas(img, self.canvas, self.white_canvas_mode)

            # Draw HUD card
            self._render_hud(output, current_mode, clear_progress)

        return av.VideoFrame.from_ndarray(output, format="bgr24")

    def _render_hud(self, frame, mode, clear_progress):
        overlay = frame.copy()
        cv2.rectangle(overlay, (15, 15), (280, 160), (20, 20, 20), -1)
        cv2.addWeighted(overlay, 0.70, frame, 0.30, 0, frame)
        cv2.rectangle(frame, (15, 15), (280, 160), (70, 70, 70), 1)

        cv2.putText(frame, "AIR CANVAS AI", (28, 42), cv2.FONT_HERSHEY_DUPLEX, 0.65, (0, 215, 255), 2)
        cv2.putText(frame, f"FPS: {int(self.fps)}", (210, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1)

        mode_color = {
            "DRAW": (0, 255, 0),
            "COLOR": (255, 200, 0),
            "ERASER": (0, 140, 255),
            "CLEAR": (0, 0, 255),
            "STANDBY": (140, 140, 140),
        }.get(mode, (200, 200, 200))

        cv2.putText(frame, f"MODE:  {mode}", (28, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.6, mode_color, 2)

        # Active Color Indicator
        active_color = PALETTE[self.color_index]
        cv2.putText(frame, f"COLOR: {active_color['name']}", (28, 105), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (230, 230, 230), 1)
        cv2.circle(frame, (170, 100), 8, active_color["bgr"], -1)
        cv2.circle(frame, (170, 100), 9, (255, 255, 255), 1)

        cv2.putText(frame, f"BRUSH: {self.brush_size}px", (28, 135), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)

        if mode == "CLEAR" and clear_progress > 0:
            bar_w = int(240 * clear_progress)
            cv2.rectangle(frame, (25, 145), (265, 155), (60, 60, 60), -1)
            cv2.rectangle(frame, (25, 145), (25 + bar_w, 155), (0, 0, 255), -1)


# -----------------------------------------------------------------------------
# Streamlit UI
# -----------------------------------------------------------------------------
st.title("🖐️ Air Canvas AI — Touchless Drawing")
st.markdown(
    "Turn your hand movements into a virtual brush using computer vision and deep learning."
)

# Sidebar Controls
st.sidebar.header("🎨 Canvas Controls")

color_choice = st.sidebar.selectbox(
    "Select Color",
    options=[c["name"] for c in PALETTE],
    index=0,
)
selected_color_idx = [c["name"] for c in PALETTE].index(color_choice)

brush_size = st.sidebar.slider("Brush Size", min_value=2, max_value=30, value=8)
eraser_radius = st.sidebar.slider("Eraser Radius", min_value=15, max_value=80, value=40)
smoothing = st.sidebar.slider("Smoothing (EMA Alpha)", min_value=0.1, max_value=1.0, value=0.55, step=0.05)
white_canvas = st.sidebar.checkbox("Digital Whiteboard Mode", value=False)

clear_btn = st.sidebar.button("🧹 Clear Canvas Now", use_container_width=True)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🖐️ Gesture Legend")
st.sidebar.markdown(
    """
    - **☝️ Index Finger Raised:** DRAW
    - **✌️ Index + Middle Raised:** CYCLE COLOR
    - **✊ Closed Fist:** ERASER
    - **🖐️ Open Palm (hold):** CLEAR CANVAS
    - **✋ Resting Hand:** STANDBY
    """
)

# WebRTC Streamer
webrtc_ctx = webrtc_streamer(
    key="air-canvas-ai",
    mode=WebRtcMode.SENDRECV,
    rtc_configuration=RTC_CONFIG,
    video_processor_factory=AirCanvasProcessor,
    media_stream_constraints={"video": True, "audio": False},
    async_processing=True,
)

# Sync Sidebar controls to Video Processor
if webrtc_ctx.video_processor:
    proc = webrtc_ctx.video_processor
    with proc.lock:
        proc.color_index = selected_color_idx
        proc.brush_size = brush_size
        proc.eraser_radius = eraser_radius
        proc.smoothing_alpha = smoothing
        proc.white_canvas_mode = white_canvas
        if clear_btn:
            proc.clear_requested = True
