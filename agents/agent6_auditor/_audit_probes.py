"""Audit probes — verify suspected weaknesses empirically."""
from __future__ import annotations

from agents.agent0_gatekeeper import Evaluator, Task


def main() -> None:
    e = Evaluator()

    # Probe 1: traversal via .. — does the evaluator catch it or does smb_push catch it?
    cases = [
        ("traversal sibling",
         r"\\192.168.8.237\RCClient\web\..\forwarder\evil.py", ".py"),
        ("traversal escape",
         r"\\192.168.8.237\RCClient\web\..\..\x.html", ".html"),
        ("trailing dir",
         r"\\192.168.8.237\RCClient\web\\", ".html"),
        ("double-prefix trick",
         r"\\192.168.8.237\RCClient\web\..\..\RCClient\forwarder\x.py", ".py"),
    ]
    for label, path, ext in cases:
        t = Task(op="push-web-ui", originating_agent="5", remote_path=path, payload_ext=ext, tag=label)
        d = e.evaluate(t)
        reason = d.rejection.reason_code if d.rejection else None
        print(f"  {label:<24} accepted={d.accepted} reject={reason}")

    print()
    # Probe 2: subdir contains-check — does `in` substring match let through crafted paths?
    t = Task(op="push-web-ui", originating_agent="5",
             remote_path=r"\\192.168.8.237\RCClient\forwarder\web\x.html",   # web inside forwarder
             payload_ext=".html", tag="sneaky")
    d = e.evaluate(t)
    print(f"  subdir substring sneaky accepted={d.accepted} reject={d.rejection.reason_code if d.rejection else None}")

    # Probe 3: dotfiles / hidden — would the evaluator accept a secret file?
    t = Task(op="push-web-ui", originating_agent="5",
             remote_path=r"\\192.168.8.237\RCClient\web\.env", payload_ext=".env", tag="dotfile")
    d = e.evaluate(t)
    print(f"  dotfile .env accepted={d.accepted} reject={d.rejection.reason_code if d.rejection else None}")

    # Probe 4: empty payload_ext
    t = Task(op="push-web-ui", originating_agent="5",
             remote_path=r"\\192.168.8.237\RCClient\web\noext", payload_ext="", tag="noext")
    d = e.evaluate(t)
    print(f"  no extension accepted={d.accepted} reject={d.rejection.reason_code if d.rejection else None}")


if __name__ == "__main__":
    main()
