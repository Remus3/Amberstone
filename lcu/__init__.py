# arch: LCU package init | section=lcu | frozen=no
"""LCU package.

Installing the lockfile-notice filter here, rather than from any one caller,
is what makes the dedupe complete: `lcu.lcu_client` cannot be imported without
importing this package first, so the filter is attached before any `LcuClient`
can exist and it covers every emitter of the notice - including the second
long-lived client whose duplicate line was 41-43 percent of every emission
measured on the daily logs. See `lcu/lockfile_notice.py` for the measurements
and for why the unit of suppression is the gap EPISODE, not the throttle
window.
"""
from lcu.lockfile_notice import install as _install_lockfile_notice

_install_lockfile_notice()
