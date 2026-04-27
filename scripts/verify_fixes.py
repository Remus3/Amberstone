import sys
results = {}
with open('tft/tft_overlay.py', encoding='utf-8') as f: src = f.read()
results['RightTop_ai_bar'] = 'def bind_force_scan(self, cb, ai_bar=None)' in src
results['uses_ctrl_right_click'] = src.count('_bind_ctrl_right_click') >= 2
results['BottomStrip_ai_bar'] = src.count('def bind_force_scan(self, cb, ai_bar=None)') >= 2
with open('coaches/tft_coach.py', encoding='utf-8') as f: src2 = f.read()
results['poll_merges_last_data'] = 'Merge fresh state' in src2 or 'ALWAYS merge' in src2
results['active_instance'] = '_active_instance = None' in src2 and 'global _active_instance' in src2
with open('coaches/tft_pbe_coach.py', encoding='utf-8') as f: src3 = f.read()
results['pbe_merges_last_data'] = 'Merge fresh state' in src3
for k,v in results.items():
    print(f"  {k}: {'PASS' if v else 'FAIL'}")
print('ALL FIXES VERIFIED' if all(results.values()) else 'SOME FIXES MISSING')
