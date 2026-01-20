import cv2
import random

import bot.base.log as logger
from bot.recog.ocr import ocr_line
from bot.recog.image_matcher import image_match
from module.umamusume.context import UmamusumeContext
from module.umamusume.asset.point import (
    CULTIVATE_RESULT_CONFIRM, GOAL_ACHIEVE_CONFIRM, GOAL_FAIL_CONFIRM,
    NEXT_GOAL_CONFIRM
)

log = logger.get_logger(__name__)


def script_not_found_ui(ctx: UmamusumeContext):
    if ctx.current_screen is not None:
        log.debug(f"NOT_FOUND_UI - Screen shape: {ctx.current_screen.shape}")
        
        try:
            from module.umamusume.asset.template import UI_CULTIVATE_RACE_LIST_2
            img_gray_full = cv2.cvtColor(ctx.current_screen, cv2.COLOR_BGR2GRAY)
            x1, y1, x2, y2 = 238, 525, 300, 588
            h, w = img_gray_full.shape[:2]
            x1c = max(0, min(w, x1)); x2c = max(0, min(w, x2))
            y1c = max(0, min(h, y1)); y2c = max(0, min(h, y2))
            roi = img_gray_full[y1c:y2c, x1c:x2c]
            res = image_match(roi, UI_CULTIVATE_RACE_LIST_2)
            if res.find_match:
                from module.umamusume.script.cultivate_task.race_handlers import script_cultivate_race_list
                script_cultivate_race_list(ctx)
                return
        except Exception as e:
            log.debug(f"Race List ROI check failed: {e}")
                
        try:
            from module.umamusume.asset.template import UI_CULTIVATE_RESULT_1
            
            img = ctx.current_screen
            img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            result = image_match(img_gray, UI_CULTIVATE_RESULT_1)
            
            if result.find_match:
                log.info("Cultivate Result 1 template matched! Clicking confirm button")
                ctx.ctrl.click_by_point(CULTIVATE_RESULT_CONFIRM)
                return
            else:
                log.debug("Cultivate Result 1 template not found")
                
        except Exception as e:
            log.debug(f"Template matching failed: {str(e)}")
        
        try:
            img = ctx.current_screen
            title_area = img[200:400, 100:620]
            title_text = ocr_line(title_area).lower()
            
            log.debug(f"OCR detected text: '{title_text[:100]}...'")
            
            result_keywords = ['rewards', 'result', 'cultivation', 'complete', 'finish']
            if any(keyword in title_text for keyword in result_keywords):
                log.info(f"Potential cultivation result detected: '{title_text[:50]}...'")
                log.info("Attempting to click cultivation result confirm button")
                ctx.ctrl.click_by_point(CULTIVATE_RESULT_CONFIRM)
                return
                
            bond_area = img[400:600, 100:620]
            bond_text = ocr_line(bond_area).lower()
            log.debug(f"Bond area OCR: '{bond_text[:100]}...'")
            if 'bond level' in bond_text or 'total fans' in bond_text:
                log.info(f"Rewards screen detected via bond/fans text: '{bond_text[:50]}...'")
                log.info("Attempting to click cultivation result confirm button")
                ctx.ctrl.click_by_point(CULTIVATE_RESULT_CONFIRM)
                return
                
        except Exception as e:
            log.debug(f"Cultivation result detection failed: {str(e)}")
    
    try:
        img = ctx.current_screen
        if img is not None:
            img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            
            title_area = img_gray[200:400, 100:620]
            title_text = ocr_line(title_area).lower()
            
            middle_area = img_gray[800:1000, 200:560]
            middle_text = ocr_line(middle_area).lower()
            
            goal_keywords = ['goal', 'complete', 'achieved', 'failed', 'next', 'finish', 'target', 'objective']
            
            combined_text = f"{title_text} {middle_text}"
            
            if any(keyword in combined_text for keyword in goal_keywords):
                log.info(f"Fallback goal screen detected: '{combined_text[:50]}...'")
                
                if any(word in combined_text for word in ['complete', 'achieved']):
                    log.info(f"Goal Achieved detected - clicking confirmation")
                    ctx.ctrl.click_by_point(GOAL_ACHIEVE_CONFIRM)
                    return
                elif any(word in combined_text for word in ['failed']):
                    log.info(f"Goal Failed detected - clicking confirmation")
                    ctx.ctrl.click_by_point(GOAL_FAIL_CONFIRM)
                    return
                elif any(word in combined_text for word in ['next']):
                    log.info(f"Next Goal detected - clicking confirmation")
                    ctx.ctrl.click_by_point(NEXT_GOAL_CONFIRM)
                    return
                else:
                    log.info(f"Generic goal screen - using standard position")
                    ctx.ctrl.click(370, 1110, "Generic goal confirmation")
                    return
            
    except Exception as e:
        log.debug(f"Goal detection fallback failed: {str(e)}")
    try:
        from module.umamusume.asset.template import REF_NEXT
        img = cv2.cvtColor(ctx.current_screen, cv2.COLOR_BGR2GRAY)
        next_match = image_match(img, REF_NEXT)
        if next_match.find_match:
            center_x = next_match.center_point[0]
            center_y = next_match.center_point[1]
            ctx.ctrl.click(center_x, center_y, "Next button")
            return
    except Exception:
        pass
    log.debug("No specific UI detected - using default fallback click")
    ctx.ctrl.click(719, random.randint(111, 216), "Default fallback click")
