"""What a client may see of an exception."""

from .. import config


def public_error(e: BaseException) -> str:
    """Exception text without the absolute paths of the host."""
    msg = str(e)[-400:]
    for p in {config.ROOT, config.CACHE, config.PCM_DIR}:
        if p:
            msg = msg.replace(p, "")
    return msg
