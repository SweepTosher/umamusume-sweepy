import time
from bot.recog.image_matcher import image_match
from module.umamusume.asset.template import (
    REF_AOHARU_RACE, REF_SELECT_OPP2, REF_ALL_RES, REF_RACE_END, REF_RACE_END2,
    REF_TEAM_SHOWDOWN, REF_NEXT, REF_ROUND_1, REF_ROUND_2, REF_ROUND_3, REF_ROUND_4,
    REF_AOHARUHAI_TEAM_NAME_0, REF_AOHARUHAI_TEAM_NAME_1,
    REF_AOHARUHAI_TEAM_NAME_2, REF_AOHARUHAI_TEAM_NAME_3
)
import bot.base.log as logger

log = logger.get_logger(__name__)


def aoharuhai_after_hook(ctx, img):
    if image_match(img[984:1025, 297:365], REF_AOHARU_RACE).find_match:
        try:
            cd = getattr(getattr(ctx, 'cultivate_detail', None), 'event_cooldown_until', 0)
            if isinstance(cd, (int, float)) and time.time() < cd:
                return True
        except Exception:
            pass
        
        try:
            h, w = img.shape[:2]
            team_roi_x1, team_roi_y1, team_roi_x2, team_roi_y2 = 70, 315, 162, 811
            team_roi_x1 = max(0, min(w, team_roi_x1))
            team_roi_x2 = max(team_roi_x1, min(w, team_roi_x2))
            team_roi_y1 = max(0, min(h, team_roi_y1))
            team_roi_y2 = max(team_roi_y1, min(h, team_roi_y2))
            team_roi = img[team_roi_y1:team_roi_y2, team_roi_x1:team_roi_x2]
            
            for team_tpl in [REF_AOHARUHAI_TEAM_NAME_0, REF_AOHARUHAI_TEAM_NAME_1, 
                             REF_AOHARUHAI_TEAM_NAME_2, REF_AOHARUHAI_TEAM_NAME_3]:
                if image_match(team_roi, team_tpl).find_match:
                    log.info("Team name selection screen detected, skipping auto-click")
                    return True
        except Exception:
            pass
        
        try:
            ti = getattr(getattr(ctx, 'cultivate_detail', None), 'turn_info', None)
            roi = img[343:389, 443:485]
            refs = [REF_ROUND_1, REF_ROUND_2, REF_ROUND_3, REF_ROUND_4]
            for i, tpl in enumerate(refs):
                try:
                    if image_match(roi, tpl).find_match:
                        if ti is not None:
                            ti.aoharu_race_index = i
                        break
                except Exception:
                    continue
        except Exception:
            pass
        ctx.ctrl.click(344, 1091, 'Aoharu race')
        return True
    
    if image_match(img[1089:1113, 318:376], REF_SELECT_OPP2).find_match:
        try:
            sc = getattr(ctx.task.detail, 'scenario_config', None)
            aoharu_cfg = getattr(sc, 'aoharu_config', None)
            ti = getattr(getattr(ctx, 'cultivate_detail', None), 'turn_info', None)
            idx = getattr(ti, 'aoharu_race_index', None)
            prs = getattr(aoharu_cfg, 'preliminary_round_selections', None)
            if isinstance(idx, int) and isinstance(prs, (list, tuple)) and 0 <= idx < len(prs):
                sel = prs[idx]
                if sel == 1:
                    ctx.ctrl.click(339, 278, 'select opp')
                    time.sleep(0.5)
                elif sel == 2:
                    ctx.ctrl.click(335, 574, 'select opp')
                    time.sleep(0.5)
                elif sel == 3:
                    ctx.ctrl.click(339, 830, 'select opp')
                    time.sleep(0.5)
        except Exception:
            pass
        ctx.ctrl.click(355, 1082, 'select opp2')
        time.sleep(0.5)
        ctx.ctrl.click(522, 930, 'select opp2 cont')
        time.sleep(0.17)
        ctx.ctrl.click(522, 930, 'select opp2 cont')
        return True
    
    if image_match(img[1204:1219, 476:597], REF_ALL_RES).find_match:
        ctx.ctrl.click(536, 1211, 'all res')
        return True
    
    if image_match(img[43:72, 123:411], REF_RACE_END).find_match:
        ctx.ctrl.click(351, 1112, 'race end')
        return True
    
    if image_match(img[1204:1228, 319:399], REF_RACE_END2).find_match:
        ctx.ctrl.click(350, 1199, 'race end2')
        return True
    
    if image_match(img[1200:1222, 467:553], REF_RACE_END2).find_match:
        ctx.ctrl.click(508, 1196, 'race end2 b')
        return True
    
    if image_match(img[7:31, 24:180], REF_TEAM_SHOWDOWN).find_match:
        ctx.ctrl.click(354, 961, 'team showdown')
        time.sleep(1)
        ctx.ctrl.click(522, 930, 'select opp2 cont')
        return True
    
    if image_match(img[1097:1124, 327:393], REF_NEXT).find_match:
        ctx.ctrl.click(360, 1112, 'next')
        return True
    
    return False
