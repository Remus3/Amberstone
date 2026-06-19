import functools
import logging
import json

def safe_coach_output(mode_name: str, write_status_fn_name: str = "_write_status_field"):
    """
    Decorator for coach `_run` or `_run_coach` methods to guarantee friendly 
    degradation on API errors, preventing raw string leaks (D14).
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except Exception as e:  # noqa: BLE001
                _msg = str(e).lower()
                if "credit balance" in _msg:
                    _status = f"({mode_name} coach paused - add API credits)"
                elif "rate" in _msg and "limit" in _msg:
                    _status = f"({mode_name} coach paused - rate limited)"
                elif "authentication" in _msg or "401" in _msg:
                    _status = f"({mode_name} coach paused - auth error)"
                elif "400" in _msg or "invalid_request" in _msg:
                    _status = f"({mode_name} coach paused - request invalid)"
                elif "timeout" in _msg:
                    _status = f"({mode_name} coach paused - API timeout)"
                elif "unreachable" in _msg or "connection" in _msg:
                    _status = f"({mode_name} coach paused - API unreachable)"
                else:
                    _status = f"({mode_name} coach paused - internal error)"
                
                logger = logging.getLogger("coach")
                logger.error("%s coach error: %s", mode_name, e)
                
                # Write safe status
                write_fn = getattr(self, write_status_fn_name, None)
                if write_fn:
                    try:
                        write_fn(_status)
                    except Exception as wr_e:  # noqa: BLE001
                        logger.error("Failed to write safe fallback for %s via %s: %s", mode_name, write_status_fn_name, wr_e)
                else:
                    # Fallback for coaches that don't implement the status writer
                    try:
                        out_path = getattr(self, "_out", None)
                        if out_path:
                            current = self._blank_artifact_data()
                            if out_path.exists():
                                try:
                                    current = json.loads(out_path.read_text(encoding="utf-8"))
                                except Exception:  # noqa: BLE001
                                    pass
                            current["immediate"] = f"Immediate: {_status}"
                            tmp = out_path.with_suffix(".tmp")
                            tmp.write_text(json.dumps(current, indent=2), encoding="utf-8")
                            tmp.replace(out_path)
                    except Exception as wr_e:  # noqa: BLE001
                        logger.error("Failed to write safe fallback for %s: %s", mode_name, wr_e)
        return wrapper
    return decorator
