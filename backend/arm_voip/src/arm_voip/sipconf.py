import os
import tempfile

from .pool import sip_password

WEBRTC_ENDPOINT = """\
[{ext}]
type=endpoint
transport=transport-ws
context={context}
disallow=all
allow=opus
allow=ulaw
allow=alaw
auth={ext}-auth
aors={ext}
webrtc=yes
dtls_auto_generate_cert=yes
direct_media=no
callerid="Operator {ext}" <{ext}>
"""

SIP_ENDPOINT = """\
[{ext}]
type=endpoint
transport=transport-udp
context={context}
disallow=all
allow=ulaw
allow=alaw
auth={ext}-auth
aors={ext}
direct_media=no
rtp_symmetric=yes
force_rport=yes
rewrite_contact=yes
callerid="Operator {ext}" <{ext}>
"""

AUTH_AND_AOR = """\
[{ext}-auth]
type=auth
auth_type=userpass
username={ext}
password={password}

[{ext}]
type=aor
max_contacts=1
remove_existing=yes
qualify_frequency=20

"""


def render_operators(
    extensions: list[str], secret: str, context: str, mode: str = "webrtc"
) -> str:
    template = WEBRTC_ENDPOINT if mode == "webrtc" else SIP_ENDPOINT
    parts = ["; Файл создан сервисом arm_voip, вручную не редактировать.\n\n"]
    for ext in extensions:
        parts.append(template.format(ext=ext, context=context) + "\n")
        parts.append(AUTH_AND_AOR.format(ext=ext, password=sip_password(secret, ext)))
    return "".join(parts)


def write_operators(path: str, content: str) -> bool:
    """Записывает конфиг атомарно. True - содержимое изменилось."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    try:
        with open(path, encoding="utf-8") as handle:
            if handle.read() == content:
                return False
    except FileNotFoundError:
        pass

    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".pjsip_")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.chmod(tmp_path, 0o644)
    os.replace(tmp_path, path)
    return True
