"""KEY=VALUE settings from /etc/versioncontrol.conf (root-owned, group _versioncontrol, mode 640). Real environment variables win."""
import os


def load_conf(path):
    out = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                out[key.strip()] = value
    except OSError:
        pass
    return out


def settings(overrides=None):
    conf = load_conf(os.environ.get("VERSIONCONTROL_CONFIG", "/etc/versioncontrol.conf"))
    conf.update({k: v for k, v in os.environ.items() if k.startswith("VERSIONCONTROL_")})
    conf.update(overrides or {})
    return conf
