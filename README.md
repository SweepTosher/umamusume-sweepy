Stuck at failed debut race award 
fix later 

![uma musume](docs/umabike.gif)

## Credits
- **Original Orginal Repository**: [UmamusumeAutoTrainer](https://github.com/shiokaze/UmamusumeAutoTrainer) by [Shiokaze](https://github.com/shiokaze)

- **This project is a detached fork of**: [UmamusumeAutoTrainer-Global](https://github.com/BrayAlter/UAT-Global-Server) by [BrayAlter](https://github.com/BrayAlter) who first ported the orginal to the global server


![UAT](docs/main.png)

---

# [GPU acceleration guide (click me later)](#gpu-setup)   

### Things this can do
- ✅ **Completely hands off**: Recover tp, Starting runs, finding the right guest cards.
  - **Everything is 100% automated you can just afk for **DAYS** until legacy umas are full**
  - **Handles everything from disconnections to the game crashing. The show will go on as long as there isn't a new update. (it handles that too now lol)**
  - **Supports background play as this runs on mobile emulators not the steam release. (You can play another game while this runs)**

- ✅ **Able to play every part of every Senario (As of writing this; URA and Unity)**
  - Is able to perform every action a human would take. From comparing skill hint levels to playing the claw machine and even deciding whether to conserve energy before summer or not. Everything you normally do this bot probably does it.

- ✅ **Supports every single uma and deckType**:
 -Every Aspect of training is customizable, If you're willing to spend time in the settings any playstyle becomes possible. For a quick overview please watch the video below as to what you can edit.      
  
(Video is outdated look at changelog or use the github search feature too check if something u want is there)

[demo.webm](https://github.com/user-attachments/assets/40a5c402-d154-4b02-8a61-96ba07e29319)


### Emulator Setup

# DO NOT LOWER YOUR FPS BELOW 30

- **Only tested on bluestacks pie64 (no longer testing on bluestacks its too unreliable) and MuMuPlayer (what I use personally)**
- **Resolution**: 720 × 1280 (Portrait mode)
- **DPI**: 180
- **Graphics**: Standard (not Simple)
- **ADB**: Must be enabled in emulator settings

## 📦 Installation & Setup
Just cd into any folder and run 

```bash
git clone https://github.com/SweepTosher/umamusume-sweepy
```

Then ensure python 3.10 is installed:

```bash
uninstall whatever python version you have

winget install -e --id Python.Python.3.10

pip install -r requirements.txt
```

After that you can just:

```bash
python main.py
```
Or just run start.bat

---

if u can follow then heres a tutorial someone made (I didn't actually watch it lol): https://youtu.be/v1m9Plw7M3Y  

## ⚠️ Important Notes

As single run mode is deprecated if you wish to emulated it you can enable "Manual skill purchase at the end" to achieve the same thing 

### Game Settings

1. **Graphics**: Must be set to `Standard`, not `Basic`
2. **Training Setup**: **Manually select** Uma Musume, Legacy, and Support Cards in-game before starting
3. **Support Cards**: Avoid friend cards (no specific outing strategy)

## 🔧 Troubleshooting
- **Stuck in menu**: disable keep alive in background in emulator settings

#### Connection Problems

- **ADB connection fails**: Close accelerators, kill adb.exe, restart emulator

### STAT CAPS (People keep messing this up)
- Under normal circumstances you want to just put a large number into all of them like so this way it will always pick the best training option
  ![alt text](docs/statCaps.png)
- HOWEVER if you keep maxxing out a stat too early for example 1000+ speed before the 2nd summer you would want to do this
  ![alt text](docs/capSpeed.png)
- Stat caps work like this
 - Soft cap  
  When at 70,80,90% to stat goal -10 20 and 30% to score respectively  
 - Hard cap  
  95% or higher will now have 0 score (IF YOU SEE THIS THERE IS A ISSUE WITH YOUR DECK AND THE BOT WILL PERFORM POORLY)
 - IT IS ENCOURAGED THAT YOU RE-EVALUATE YOUR DECK INSTEAD. THIS WAY THE BOT CAN CLICK THE BEST OPTION 100% OF THE TIME INSTEAD OF ARTIFICIALLY LIMITING AND CLICKING A WORSE OPTION 


![uma](docs/flower.gif)  


## Changelogs 
- **11/1/2025**
Go to races instead of wit training when low training score and energy is near full
Base scores for training facilities


- **27/12/2025**  
Event list updated.    
Cache to improve speed.    
More auto recovery.     
twinturbo.png        

- **25/12/2025**  
Showtime mode ui stuck fix.      
Always find and click next.png as a last resort     
made gpu public (due to increase in speed getting stuck due to slow load times are now more common) hence       
made decision making restart if ocr/template match isnt used for 10 seconds    

- **23/12/2025**  
fixed date phrasing fail causing a loop.
go update requirements.txt thx     

- **21/12/2025**  
Logging in from your phone/another device now causes the current task to pause.     
Forced brightness check again everytime infirmary is pressed.

- **19/12/2025**  
Exposed event weight to webui for user to configure.     
<img width="904" height="705" alt="{63DC8091-9B58-4229-B56C-5C8B3A74CA56}" src="https://github.com/user-attachments/assets/69f749bc-e8bb-4edf-b707-52538e64cb6b" />   


- **16/12/2025**  
Event list updated.   

- **14/12/2025**  
Having 2+ rainbow now applies a 7.5% multiplier for every additional rainbow above 1.    
Fixed spirit explosions and special training not respecting user inputs.   

- **13/12/2025**  
Minimum score before conserving energy before summer and minimum score before forcing wit training are now customizable.   

- **12/12/2025**  
Fixed recreation breaking training (forcing wit) when pal outing is configured with no pal notification. (OH I DIDNT FUCKING PUSH)  

- **11/12/2025**  
bug fixes I'm not gonna bother listing.   

- **9/12/2025**  
Fixed outing not having priority over rest  

- **9/12/2025**  
Pal Cards are good to go  
Fixed yesterday's infinite loop fuck up
Custom scoring for Finale dates   
Made pal outing override rest if all conditions are met and max energy threshold < 90.  
Added option to override insufficient fans forced races  
Blacklisted event name '' to prevent misclicks and slightly speed things up  

- **8/12/2025**  
Updated event list  
Added custom card names  
<img width="1210" height="376" alt="image" src="https://github.com/user-attachments/assets/f97186c2-6dc0-4c9c-a583-0b134d1dfa69" />

Added custom thresholds to go outing for pal event chains (DO NOT USE PAL CARDS YET FEEL FREE TO HELP TEST AND DEBUG BUT PAL CARDS STILL SUCK IM NOT DONE WITH THEIR TRAINING FACILITY SCORING)  
<img width="1036" height="363" alt="{E79E2232-EFF0-4976-8FD8-1278503DFFBB}" src="https://github.com/user-attachments/assets/f0901600-3fb4-49d4-87a5-00ab36efda0e" />

- **5/12/2025**   
Added a overwrite for event "Training" to click the 5th choice if 5 choices are detected (apparently people are still getting stuck there somehow)
Training tweaks. Energy management should be more effecient now  

- **30/11/2025**   
added -10% score penalty to the highest stat in senior year to hopefully balance stats out (experimental might remove).  

- **29/11/2025**   
Fixed getting stuck at aoharu tutorial event sometimes  
Updated event list    
Added Select/Deselect all skills blacklist/priority based on whats being searched  
Dropped repetitive clicks recovery reset threshold from 5 to 2   

- **28/11/2025**  
Maybe fixed bot getting stuck sometimes after ending a career.    
Maybe fixed bot restarting and wasting time sometimes when detecting a event.  
Skill hint level detection; Will now purchase the highest skill hint level of each priority before moving on to the next priority.  

- **22/11/2025**  
Added drag and drop of skills between priorities and blacklist (Drag them outside into nothing to deselect completely)  

- **16/11/2025**  
Attempted to fix some crashes   
patched up team trials execution mode  

- **15/11/2025**  
updated some support card names  
aoharu (unity cup) team name selection works now

- **14/11/2025**  
updated skill list  
Fixed getting stuck in support card selection
Stat cap score calc hard cap
default target attributes changed  

- **12/11/2025**   
"Use last selected parents" Option added in webui.  
support for team trials quick mode

- **10/11/2025 (Game Updated)**  
Fixed bot breaking
- **10/11/2025**   (forgot to push lol)  
Enemy team selection for races 1 2 3 4 (aoharu)  
Fixed "Auto select team" taking forever (aoharu)  
- **10/10/2025**   
Bare minimum aoharu implementation. (60%)
  - able to reach the end assuming you already beat team zenith
  - customizable special training parameters
  - customizable spirit explosion parameters
  - ignore wit spirit explosions when energy high bonus score to wit spirit explosion if energy low

  Customizable and more intuitive "Stuck" handling 
- **26/10/2025**   
Made it easier to customize event choices
- **25/10/2025**   
Maybe fixed buying skills  
Prep for aoharu hai
- **20/10/2025**   
Stuck clicking something failsafe part 2
- **19/10/2025**   
waste time (UI changes)  
Fuzzy matching for buying skills (still sucks but should be a little better)
- **18/10/2025**   
Customizable energy limit.  
Option to adjust score based on training failure rate
- **29/9/2025**   
Soft reset after every task. Should help with memory issues.  
- **28/9/2025**   
Team trials execution mode. not tested and held together by hopes and dreams so its probably gonna break half the time.  
Maybe fix card selection breaking

## Planned/In progress (In order from top to bottom)
- starting work on full auto mode gonna have no other updates for a while   
- im going to uma my musumes 


## GPU Setup

This bot can optionally use an NVIDIA GPU to accelerate certain operations. Follow these steps:

1. Install drivers for your NVIDIA GPU.
2. Install **CUDA Toolkit 11.8**: [NVIDIA CUDA Toolkit](https://developer.nvidia.com/cuda-11-8-0-download-archive)
3. Install **cuDNN v8.6.0 (October 3rd, 2022) for CUDA 11.x**

   * Download the ZIP folder from [NVIDIA cuDNN](https://developer.nvidia.com/rdp/cudnn-archive)
4. Extract the ZIP and move its contents to the respective CUDA folders for example:

   ```
   cudnn-windows-x86_64-8.6.0.163_cuda11-archive\cudnn-windows-x86_64-8.6.0.163_cuda11-archive\bin
   → C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.8\bin
   ```

   You are to do this for all the folders
   
5. Add the following three folders to your system **PATH**:

   * `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.8\bin`
   * `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.8\libnvvp`
   * `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.8`
6. Copy this file:

   ```
   C:\Program Files\NVIDIA Corporation\Nsight Systems 2022.4.2\host-windows-x64\zlib.dll
   ```

   and paste it into:

   ```
   C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.8\bin
   ```

   Rename it to `zlibwapi.dll`.

7. Uninstall CPU version of PaddlePaddle:
```bash
pip uninstall paddlepaddle
```

8. Install GPU version of PaddlePaddle:
```bash
pip install paddlepaddle-gpu==2.6.2 -i https://pypi.tuna.tsinghua.edu.cn/simple
```

9. Update `requirements.txt` to prevent reinstalling CPU version:
```bash
Open requirements.txt and change line 71 from:
paddlepaddle==2.6.2

to:
paddlepaddle-gpu==2.6.2
```
Reboot

That should be all iirc if not go make a issue


Keep shilling this shit on /vg/ with the retarded forced meme ur making me look good


<img width="190" height="140" alt="image" src="https://github.com/user-attachments/assets/105b0349-2b69-4984-bbbc-c76fbe762e79" />
<img width="190" height="140" alt="image" src="https://github.com/user-attachments/assets/65edac1a-91c0-4559-8393-7432418afa18" />
<img width="190" height="140" alt="image" src="https://github.com/user-attachments/assets/3193d3ce-2a3a-4a77-9ed6-c04702083b60" />
<img width="190" height="140" alt="image" src="https://github.com/user-attachments/assets/d58f6376-76c7-455e-a16d-9bb9d92db969" />
<img width="190" height="140" alt="image" src="https://github.com/user-attachments/assets/d097751f-966f-4f3f-ba5b-3608cac6bdbe" />
<img width="190" height="140" alt="image" src="https://github.com/user-attachments/assets/671eb304-cb0b-4f02-9023-ea313df2f987" />
<img width="190" height="140" alt="image" src="https://github.com/user-attachments/assets/f1ecf7d6-1e18-45d6-8143-66b877d9c786" />
<img width="190" height="140" alt="image" src="https://github.com/user-attachments/assets/94ea9609-54db-4322-a0f3-9168a70932e0" />
<img width="190" height="140" alt="image" src="https://github.com/user-attachments/assets/d64d2197-217f-40c5-a57e-3ccd5c868e2d" />
<img width="190" height="140" alt="image" src="https://github.com/user-attachments/assets/cacd2cf3-b880-4b1e-8818-af33a30bcf38" />







