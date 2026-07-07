"""Pure routing policy for RC Budget-Saver. LiteLLM realizes error/ctx fallbacks at
runtime; this documents+tests the intent and lets the monitor predict the route.
Tier convention = RC R5: 0/1 routine, 2 engine/scorer, 3 hard/arch."""
LOCAL_CTX_BUDGET = 24_000  # usable local window on 12GB w/ q8_0 KV (VERIFY-AT-BENCH via C9)

def choose_model(est_tokens: int, tier: int, privacy: bool) -> str:
    if privacy:
        return "rc-local"                    # never leaves the machine, accept quality hit
    if tier >= 3:
        return "DEFER-TO-CLAUDE"             # do not thrash the cheap brain
    if est_tokens > LOCAL_CTX_BUDGET:
        return "rc-deepseek"                 # local KV would overflow
    if tier >= 2:
        return "rc-deepseek"                 # engine/scorer -> stronger brain
    return "rc-local"                        # routine, small ctx -> tokenless local
