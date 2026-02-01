# Sweepy — /vg/'s Uma Musume Bot (UAT REHASHED)

### A umamusume bot that handles all aspects of gameplay including training, races, events, skill purchasing, and starting runs. 

![Uma Musume Auto Trainer](docs/main.png)

---

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Emulator Setup](#emulator-setup)
- [Configuration](#configuration)
- [Stat Caps Guide](#stat-caps-guide)
- [GPU Acceleration](#gpu-acceleration)
- [Troubleshooting](#troubleshooting)
- [Changelog](#changelog)
- [Credits](#credits)

---

## Features

### Fully Automated Training
- Completely hands-off operation for days of continuous training
- Automatic TP recovery and run initialization
- Handles disconnections, crashes, and game updates automatically
- Background play support via mobile emulators
- Able to generate over a dozen 3* parents a week if left to run

### Scenario Support
- URA Finals scenario
- Unity Cup (Aoharu)


### Comprehensive Customization
- Literally everything that can be detected is detected and used for customization.
- Skill hint levels, Energy Changes, Stat gains.
- Hundreds of settings for you to tune the bot to your liking.


---

## Requirements

- Python 3.10
- Visual C++ Redistributable ([Download](https://aka.ms/vs/17/release/vc_redist.x64.exe))
- Android emulator (BlueStacks Pie64 or MuMu Player recommended)

---

## Installation

### Step 1: Clone the Repository

```bash
git clone https://github.com/SweepTosher/umamusume-sweepy
cd umamusume-sweepy
```

### Step 2: Install Python 3.10

```bash
winget install -e --id Python.Python.3.10
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Run the Bot

```bash
python main.py
```

Alternatively, run `start.bat` to launch the bot.

---

## Emulator Setup

### Display Settings
- **Resolution**: 720 x 1280 (Portrait mode)
- **DPI**: 180
- **FPS**: 30 or higher (do not set below 30)

### Graphics Settings
- **Rendering**: Standard (not Simple/Basic)
- **ADB**: Must be enabled in emulator settings

### Supported Emulators
- MuMu Player (recommended)
- BlueStacks Pie64

---

## Configuration

1. Set graphics to `Standard` in-game (not `Basic`)
2. Manually select your Uma Musume, Legacy Uma, and Support Cards before starting

---

## Stat Caps Guide

Stat caps control how the bot prioritizes training based on current stat values.

### Default Configuration
For normal operation, set large values for all stat caps to always select the optimal training:

![Default Stat Caps](docs/statCaps.png)

### Custom Caps for Specific Builds
If a stat maxes out too early (e.g., 1000+ speed before second summer), adjust caps accordingly:

![Speed Cap Example](docs/capSpeed.png)

### How Stat Caps Work
- **Soft Cap**: At 70%, 80%, 90% of target, applies -10%, -20%, -30% score penalty respectively
- **Hard Cap**: At 95% or higher, score becomes 0 (indicates deck optimization needed)

Adjusting your deck composition is recommended over relying on artificial stat caps.

---

## GPU Acceleration

Optional NVIDIA GPU acceleration for improved performance.

### Prerequisites
1. NVIDIA GPU with current drivers
2. CUDA Toolkit 11.8 ([Download](https://developer.nvidia.com/cuda-11-8-0-download-archive))
3. cuDNN v8.6.0 for CUDA 11.x ([Download](https://developer.nvidia.com/rdp/cudnn-archive))

### Installation Steps

1. Extract cuDNN and copy contents to CUDA installation folders:
   ```
   cudnn-windows-x86_64-8.6.0.163_cuda11-archive\bin
   -> C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.8\bin
   ```
   Repeat for all cuDNN folders (bin, include, lib).

2. Add to system PATH:
   - `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.8\bin`
   - `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.8\libnvvp`
   - `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.8`

3. Copy and rename zlib:
   ```
   C:\Program Files\NVIDIA Corporation\Nsight Systems 2022.4.2\host-windows-x64\zlib.dll
   -> C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.8\bin\zlibwapi.dll
   ```

4. Install GPU version of PaddlePaddle:
   ```bash
   pip uninstall paddlepaddle
   pip install paddlepaddle-gpu==2.6.2 -i https://pypi.tuna.tsinghua.edu.cn/simple
   ```

5. Update `requirements.txt` line 71:
   ```
   paddlepaddle-gpu==2.6.2
   ```

6. Reboot system.

---

## Troubleshooting

### Bot Stuck in Menu
Disable "Keep alive in background" in emulator settings.

### ADB Connection Fails
Restart your machine

### Stats Not Showing in Scoring
Install or reinstall Visual C++ Redistributable:
- [Download vc_redist.x64.exe](https://aka.ms/vs/17/release/vc_redist.x64.exe)

![Stats Display](https://github.com/user-attachments/assets/1f68af35-cf9d-41ce-9392-c26ecf83cc70)

---

## Changelog

### 2025-01-26
- Energy gain/loss now affects scoring.

### 2025-01-26
- Gear icon now stops task and copies task info to new task creation popup

### 2025-01-25
- Improved detection methods using stat gains instead of rainbow count
- Fixed accidental team rank button clicks

### 2025-01-16
- Faster scrolling
- Trainer test event support

### 2025-01-11
- Race fallback when low training score and high energy
- Base scores for training facilities

### 2024-12-27
- Event list updated
- Cache improvements for speed
- Additional auto recovery options

### 2024-12-25
- Showtime mode UI fix
- Improved fallback click handling
- GPU acceleration public release
- Decision making restart after 10 seconds of inactivity

### 2024-12-23
- Fixed date parsing loop issue

### 2024-12-21
- Pause task when logged in from another device
- Brightness check on infirmary press

### 2024-12-19
- Event weight configuration exposed in web UI

### 2024-12-16
- Event list updated

### 2024-12-14
- Rainbow training bonus: 7.5% multiplier per additional rainbow above 1
- Fixed spirit explosions and special training input handling

### 2024-12-13
- Customizable summer energy conservation threshold
- Customizable wit training fallback threshold

### 2024-12-12
- Fixed recreation breaking training with pal outing configuration

### 2024-12-09
- Fixed outing priority over rest
- Pal card support improvements
- Custom scoring for finale dates
- Pal outing override for rest conditions
- Option to override insufficient fans forced races

### 2024-12-08
- Updated event list
- Custom card names support
- Pal event chain outing thresholds

### 2024-12-05
- Event "Training" 5th choice override
- Improved energy management

### 2024-11-30
- Highest stat penalty in senior year (-10%) for stat balancing

### 2024-11-29
- Fixed Aoharu tutorial event loop
- Updated event list
- Skill blacklist select/deselect all
- Reduced repetitive click threshold

### 2024-11-28
- Post-career completion fix
- Event detection optimization
- Skill hint level detection for prioritized purchasing

### 2024-11-22
- Drag and drop skill management between priorities and blacklist

### 2024-11-16
- Crash fixes
- Team trials execution mode improvements

### 2024-11-15
- Updated support card names
- Aoharu team name selection fix

### 2024-11-14
- Updated skill list
- Fixed support card selection issues
- Stat cap hard cap calculation
- Default target attribute changes

### 2024-11-12
- "Use last selected parents" option
- Team trials quick mode support

### 2024-11-10
- Game update compatibility fix
- Enemy team selection for Aoharu races
- Fixed auto team selection performance

### 2024-10-10
- Aoharu implementation (60%)
- Customizable special training and spirit explosion parameters
- Improved stuck handling

---

## Credits

- **Original Repository**: [UmamusumeAutoTrainer](https://github.com/shiokaze/UmamusumeAutoTrainer) by [Shiokaze](https://github.com/shiokaze)
- **Global Server Port**: [UmamusumeAutoTrainer-Global](https://github.com/BrayAlter/UAT-Global-Server) by [BrayAlter](https://github.com/BrayAlter)

---

![Uma Musume](docs/umabike.gif)
![Uma Musume](docs/flower.gif)
<img width="190" height="140" alt="image" src="https://github.com/user-attachments/assets/a376b9e0-832e-45ea-add4-499a9f76a284" />
<img width="190" height="158" alt="image" src="https://github.com/user-attachments/assets/428a7704-0729-4dc3-890f-246fb0a94774" />
<img width="190" height="140" alt="image" src="https://github.com/user-attachments/assets/65edac1a-91c0-4559-8393-7432418afa18" />
<img width="190" height="140" alt="image" src="https://github.com/user-attachments/assets/3193d3ce-2a3a-4a77-9ed6-c04702083b60" />
<img width="190" height="140" alt="image" src="https://github.com/user-attachments/assets/d58f6376-76c7-455e-a16d-9bb9d92db969" />
<img width="190" height="140" alt="image" src="https://github.com/user-attachments/assets/d097751f-966f-4f3f-ba5b-3608cac6bdbe" />
<img width="190" height="140" alt="image" src="https://github.com/user-attachments/assets/671eb304-cb0b-4f02-9023-ea313df2f987" />
<img width="190" height="140" alt="image" src="https://github.com/user-attachments/assets/f1ecf7d6-1e18-45d6-8143-66b877d9c786" />
<img width="190" height="140" alt="image" src="https://github.com/user-attachments/assets/94ea9609-54db-4322-a0f3-9168a70932e0" />
<img width="190" height="140" alt="image" src="https://github.com/user-attachments/assets/d64d2197-217f-40c5-a57e-3ccd5c868e2d" />
<img width="190" height="140" alt="image" src="https://github.com/user-attachments/assets/cacd2cf3-b880-4b1e-8818-af33a30bcf38" />
<img width="190" height="140" alt="image" src="https://github.com/user-attachments/assets/3bdd80ec-cb77-4637-9f61-e3f8fab8d85d" />
<img width="317" height="317" alt="image" src="https://github.com/user-attachments/assets/61c4c0dd-85bc-4517-84c1-021fcf5d47fa" />
