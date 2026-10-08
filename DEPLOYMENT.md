# 🚀 Air Canvas AI — Complete Deployment Guide

This guide covers how to deploy and distribute **Air Canvas AI** using two complementary methods:
1. **Cloud Web Deployment** (Free public link for anyone to try in their browser via webcam)
2. **Windows Standalone App (`.exe`)** (Single-click desktop app without installing Python)

---

## 🌐 Method 1: Deploy Live on the Web (Free)

With WebRTC and Streamlit, users anywhere in the world can open your link, grant camera permission in their browser, and interact touchlessly.

### Option A: Deploy to Hugging Face Spaces (Recommended - Easiest & 100% Free)

1. **Sign Up / Log In**:
   - Go to [Hugging Face](https://huggingface.co) and create a free account.

2. **Create a New Space**:
   - Go to **Spaces** ➔ Click **Create new Space**.
   - Name your space: `air-canvas-ai`.
   - Select License: `MIT` (or `Apache 2.0`).
   - **Space SDK**: Select **Streamlit**.
   - Space Hardware: **CPU basic (Free - 2 vCPU · 16GB)**.
   - Click **Create Space**.

3. **Upload Files**:
   In the Files tab of your new Space, upload the following files from your local project:
   - [`app.py`](app.py) ➔ Main application file.
   - [`requirements_web.txt`](requirements_web.txt) ➔ **Rename this file to `requirements.txt`** when uploading to Hugging Face.
   - [`packages.txt`](packages.txt) (Optional, for Linux system dependencies):
     ```text
     libgl1-mesa-glx
     libglib2.0-0
     ```

4. **Launch**:
   Hugging Face will automatically build the environment and start the app.
   Your live link will be:
   `https://huggingface.co/spaces/<your-username>/air-canvas-ai`

---

### Option B: Deploy to Streamlit Community Cloud (via GitHub)

1. **Push your code to GitHub**:
   Ensure [`app.py`](app.py) and [`requirements_web.txt`](requirements_web.txt) are committed to your GitHub repository.

2. **Deploy on Streamlit**:
   - Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
   - Click **New app**.
   - Repository: `your-username/air-canvas-ai`
   - Branch: `main`
   - Main file path: `app.py`
   - Advanced settings: Set Python version to `3.10` or `3.11`.
   - Click **Deploy!**

3. Your public URL will be ready at:
   `https://air-canvas-ai.streamlit.app`

---

## 💻 Method 2: Package as a Standalone Windows Executable (`.exe`)

Distribute a desktop version that runs on any 64-bit Windows machine without needing Python, git, or command lines installed.

### How to Build:

1. In the project directory, simply double-click:
   **[`build_exe.bat`](build_exe.bat)**

   *(Or run manually in PowerShell)*:
   ```powershell
   .\.venv\Scripts\pyinstaller.exe --noconfirm --onedir --windowed --name "AirCanvasAI" --collect-all mediapipe --collect-all cv2 main.py
   ```

2. Once the build finishes, your executable will be located in:
   `dist\AirCanvasAI\AirCanvasAI.exe`

3. **How to Distribute**:
   - Right-click the `dist\AirCanvasAI` folder ➔ **Send to** ➔ **Compressed (zipped) folder**.
   - Rename to `AirCanvasAI-v1.0-Windows.zip`.
   - Go to your GitHub repository ➔ **Releases** ➔ **Draft a new release**.
   - Attach `AirCanvasAI-v1.0-Windows.zip` as a binary release asset.

---

## 🧪 Local Testing Before Deploying

You can test both versions locally right now:

* **Desktop Version (OpenCV GUI)**:
  Double-click [`run.bat`](run.bat) or run:
  ```powershell
  .\.venv\Scripts\python.exe main.py
  ```

* **Web Version (Streamlit WebRTC)**:
  Double-click [`run_web.bat`](run_web.bat) or run:
  ```powershell
  .\.venv\Scripts\streamlit.exe run app.py
  ```
  Your browser will open to `http://localhost:8501`.
