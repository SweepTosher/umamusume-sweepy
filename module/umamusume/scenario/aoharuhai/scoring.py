import time
from bot.conn.fetch import read_energy


def adjust_spirit_explosion_weight(ctx, idx, score, spirit_counts, current_energy):
    if idx == 4 and spirit_counts[idx] > 0:
        se_w = ctx.cultivate_detail.spirit_explosion[idx] if idx < len(ctx.cultivate_detail.spirit_explosion) else 0.0
        if se_w != 0.0:
            try:
                energy = int(read_energy())
                if energy == 0:
                    time.sleep(0.37)
                    energy = int(read_energy())
            except Exception:
                energy = None
            if energy is not None:
                if energy > 80:
                    return score
                elif energy < 10:
                    return score
                else:
                    bonus = se_w * 1.37
                    return score + bonus
    return score
