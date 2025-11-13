thonimport logging
import random
import time
from typing import Tuple

logger = logging.getLogger(__name__)

def sleep_with_jitter(min_seconds: float = 1.0, max_seconds: float = 3.0) -> float:
    """
    Sleep for a random duration between min_seconds and max_seconds.

    Returns the actual sleep duration so callers can log or test around it.
    """
    if min_seconds < 0 or max_seconds < 0:
        logger.warning(
            "Negative values passed to sleep_with_jitter(min_seconds=%s, max_seconds=%s); "
            "clamping to non-negative.",
            min_seconds,
            max_seconds,
        )
        min_seconds = max(min_seconds, 0.0)
        max_seconds = max(max_seconds, 0.0)

    if max_seconds < min_seconds:
        logger.debug(
            "Swapping min_seconds and max_seconds because %s > %s.",
            min_seconds,
            max_seconds,
        )
        min_seconds, max_seconds = max_seconds, min_seconds

    delay = random.uniform(min_seconds, max_seconds)
    logger.debug("Sleeping for %.2f seconds to be polite.", delay)
    time.sleep(delay)
    return delay

def validate_delay_range(delay_range: Tuple[float, float]) -> Tuple[float, float]:
    """
    Normalize a delay range tuple to ensure it is safe and sensible.
    """
    min_s, max_s = delay_range
    min_s = max(0.0, float(min_s))
    max_s = max(0.0, float(max_s))

    if max_s < min_s:
        min_s, max_s = max_s, min_s

    if min_s == max_s == 0.0:
        # Avoid hammering the remote host if a zero delay is configured
        logger.warning("Zero delay range configured; forcing minimal delay of 0.5-1.0 seconds.")
        return 0.5, 1.0

    return min_s, max_s